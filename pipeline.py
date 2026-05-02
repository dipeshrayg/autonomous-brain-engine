"""
pipeline.py - Multi-stage LLM code-generation pipeline.

Stages (now with multi-model conferences for plan + critique):
    1. PLAN       - 3-way architect conference (Mistral-Large + Llama-70B propose,
                    GPT-4o judges and synthesizes).
    2. IMPLEMENT  - per-file generation by the Engineer role (gpt-4o).
    3. CRITIQUE   - 2-way reviewer conference (Mistral-Large + Llama-70B), merged.
    4. FIX        - the Fixer role (gpt-4o-mini) applies specific issues.
    5. POLISH     - the Polisher role (gpt-4o-mini) elevates UX.

The orchestrator wraps stages 3+4 in a quality loop until the project is clean
or MAX_QUALITY_CYCLES is exhausted. Hard advancement constraints are enforced
in `_validate_plan` so a stale, low-complexity plan never reaches code-gen.

Each role's model assignment + fallback chain lives in `roles.py`. Rate limits
on the GitHub Models free tier are per-model, so spreading load across model
families lets the system run multiple projects per day without exhausting any
one budget.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

import roles

log = logging.getLogger("brain.pipeline")


class PipelineError(RuntimeError):
    pass


# ─────────────────────── Prompts ────────────────────────────────────────

PLAN_SYSTEM = """You are the Chief Architect of an autonomous, twice-daily software-creation pipeline. You design at the intersection of a polymath developer with all of these hats: full-stack, frontend, backend, server-side, DevOps, web designer, system & cybersecurity, data engineer, AI/ML researcher, VP of Engineering, product manager, business analyst, networking specialist, trading / quantitative analyst, distributed-systems architect. Each project today reflects that breadth.

ABSOLUTE CONSTRAINTS - non-negotiable:
1. Comply strictly with GitHub TOS / Acceptable Use. No active malware, no exfiltration, no exploits against systems without consent. Security/trading topics are educational/diagnostic ONLY (operate on synthetic data, simulate, never connect to real markets or real targets).
2. The project MUST run in any modern browser by serving a single index.html via GitHub Pages — no install, no build step. Allowed runtimes: HTML+CSS+JavaScript, Canvas 2D, SVG, optionally Web Audio / Web Workers / IndexedDB. PREFER Canvas 2D over WebGL (verifier runs software-rendered Chromium). If you must use WebGL/WebGPU, include a fallback notice when the context can't be created. ABSOLUTELY NO COMPILED LANGUAGES — never plan .ts, .jsx, .tsx, .scss, .less, .vue, .svelte files. Write plain .js, .html, .css. There is no transpiler. If your plan needs `dist/` paths, list those exact .js files as project files yourself.

3. HARD ADVANCEMENT (the most important rule):
   - complexity_score is OPEN-ENDED. NO upper cap. It must be >= max(recent complexity_scores) + 1.
     Scale guide:
       1-3   trivial demo
       4-6   solid single-file interactive demo
       7-9   polished real-time interactive system, multiple controls
       10-12 production-style with multiple subsystems, simulated backend, persistence
       13-15 full-app feel: multi-view, simulated auth, complex state, multiple integrated panels
       16-20 architectural feat: IDE-quality tooling, multi-pane workspace, deep interactivity
       21+   surpass even that — invent the next rung
   - novel_concepts must contain >=2 concepts NOT in concepts_explored.
   - tech_stack must include at least one library/technique no previous project has used.
   - advancement_axis must explicitly explain how today exceeds the most recent project along a concrete dimension.

4. PATTERN ROTATION — no two consecutive projects share a pattern:
   `pattern` must be a project genre/shape. Choose ONE that does NOT appear in `patterns_used` for the last 5 projects. Examples (you may invent more):
     visualizer, simulator, game, generator, dashboard, editor, analyzer,
     explorer, sandbox/IDE, tutor, comparator, planner, monitor, transformer,
     studio, calculator, terminal, modeler, debugger, composer, mapper,
     orchestrator, replayer, profiler.

5. DOMAIN ROTATION — broad coverage of the polymath catalogue:
   `domain` must be a top-level field of expertise this project explores. Choose ONE that does NOT appear in `domains_used` for the last 5 projects. The catalogue (extend freely):
     AI/ML, Trading & Markets, Cybersecurity, Networking, Data Engineering,
     DevOps/SRE, Web Design, UX/Product, Cryptography, Compilers/Languages,
     Distributed Systems, Game Theory, Operations Research, Computer Graphics,
     3D/WebGL, Audio/DSP, Bioinformatics, Education, System Architecture,
     Database Engineering, Compiler Theory, Embedded/IoT, Robotics,
     Financial Engineering, Statistical Inference, Information Theory,
     Algorithmic Composition, Visualization Theory.

6. SUBSTANTIVE SCOPE that scales with complexity:
   - complexity 7-9: >=4 source files (excluding README), >=400 LOC.
   - complexity 10-12: >=6 source files, >=700 LOC, simulated persistence (IndexedDB/localStorage).
   - complexity 13+: >=8 source files, >=1000 LOC, multi-view layout, keyboard shortcuts, save/load state.
   Real depth: multiple algorithms, real-time interactivity, polished UI, edge case handling, accessible markup.

7. UI REQUIREMENTS the verifier checks mechanically:
   - >=3 interactive controls (>=5 for complexity 10+).
   - <meta name="viewport">.
   - Canvas (if any) renders meaningful content on first frame.

8. VISUAL IDENTITY — every project must feel distinct:
   - Don't reuse the same colour palette twice in a row. Vary typography (serif vs mono vs sans), layout (single-pane vs split-pane vs multi-panel grid), and visual personality.
   - Polished by default: thoughtful spacing, clear hierarchy, hover/focus states, prefers-color-scheme support.

9. EXTERNAL LIBRARIES — ABSOLUTE RULE:
   Every external library MUST come from a pinned CDN URL (jsdelivr / unpkg / cdnjs) with explicit version. NEVER write <script src="some-lib.js"> referencing a local library file you are not generating. The verifier mechanically checks every src/href local reference resolves to a file that exists. Dangling refs = hard fail.

OUTPUT — single JSON object, no prose, no markdown fences:
{
  "name": "kebab-case (3-60 chars, ascii)",
  "description": "≤200 chars",
  "long_description": "2-4 paragraphs for README",
  "language": "primary language",
  "tech_stack": [list of specific libs/APIs],
  "complexity_score": int >=1 (no upper cap),
  "concepts_demonstrated": [list],
  "novel_concepts": [list of concepts NOT in concepts_explored],
  "advancement_axis": "explicit explanation of how this exceeds recent projects",
  "pattern": "one genre token, NOT in patterns_used[-5:]",
  "domain": "one domain token, NOT in domains_used[-5:]",
  "visual_identity": "short description of color palette, typography, layout personality",
  "is_web_project": true,
  "safety_notes": "...",
  "architecture": {
    "overview": "high-level architecture",
    "data_flow": "how data flows between modules",
    "key_algorithms": ["alg 1: brief", "alg 2: brief"]
  },
  "files": [
    {"path": "relative/path.ext",
     "role": "what this file does (1-2 sentences)",
     "key_functions": ["fn or section names"]}
  ],
  "ui_features": ["specific user controls and what they do"],
  "verification_criteria": ["specific things that must work after the page loads"]
}
"""


IMPLEMENT_SYSTEM = """You are implementing ONE file of a multi-file project that has already been architected. You will receive: the full plan, any sibling files already written, and the file you must produce. Your output is the complete file content.

RULES:
- Production-quality code. NO TODOs, NO placeholders, NO "implement this later", NO stubs.
- Honor sibling files: do not redefine variables/functions they already export, do not duplicate their work.
- For HTML: <!DOCTYPE html>, charset, viewport, semantic structure. All referenced scripts/styles must exist in sibling files. PREFER CLASSIC <script src="..."></script> over <script type="module">. Classic scripts compose reliably without import maps; modules require careful path handling that often breaks under GitHub Pages.
- ABSOLUTELY NO COMPILED-LANGUAGE FILES. The runtime is a static GitHub Pages server — there is no build step. NEVER write .ts (TypeScript), .jsx, .tsx, .scss, .less, .vue, .svelte, .coffee, or any other file that would normally be transpiled. Write plain .js, .html, .css. If you reference dist/foo.js or build/bar.js, that file must EXIST in your `files` list as a concrete static asset.
- For JS: handle DOMContentLoaded properly, no top-level statements that touch the DOM before it's ready, handle resize, handle edge cases, no unhandled promise rejections. AVOID Web Workers unless absolutely essential — they require separate worker.js files and cross-file message protocol that frequently breaks. Inline computation is fine for nearly all interactive demos.
- For CSS: responsive, accessible, polished — use modern selectors, custom properties, prefers-color-scheme.
- Pin any CDN versions explicitly (e.g., d3@7.8.5).
- ABSOLUTE RULE: every <script src="..."> and <link href="..."> with a relative URL MUST refer to a file that is actually present in this project's `files` list. If you need an external library, use a pinned CDN URL (https://cdn.jsdelivr.net/npm/<pkg>@<version>/<file>). Never write `src="some-lib.js"` and assume someone will provide it.
- Define every function, class, and global your sibling files reference. If app.js calls `setupNodeControls()`, then somewhere that function must exist. Every cross-file reference must resolve.
- The result must be runnable as-is when served statically by GitHub Pages.

OUTPUT - single JSON, no prose, no fences:
{"path": "<path you were asked to write>", "content": "<full file content>"}
"""


CRITIQUE_SYSTEM = """You are a senior engineer doing a brutal pre-ship code review. Be ruthless and specific. The goal is: ship a flawless project.

You receive:
- The plan (with verification_criteria and ui_features the project promised).
- The current source files.
- A browser verification report (console errors, page errors, DOM/canvas/interactive metrics from a real headless Chrome run).

Find every:
- Bug: syntax / logic / race / off-by-one / null deref / async error.
- Missing feature: anything verification_criteria or ui_features promised but the code doesn't deliver.
- UX gap: missing controls, no feedback, no labels, no instructions, broken on resize, jaggy animation, no error handling.
- Shallow visualization: a "visualizer" that draws static dots, single-line traces, blank canvas, etc.
- Edge case: empty inputs, extreme values, very fast clicks, tab going to background.
- Performance: O(n²) where O(n) works, allocs in hot loop, blocking main thread.
- Polish: ugly defaults, missing dark mode, no transitions, unprofessional typography.

DO NOT obsess over: GPU/WebGL performance warnings (e.g. "GL_CLOSE_PATH_NV", "GPU stall"), favicon 404s, autoplay policy hints. These are environmental noise, not bugs.

OUTPUT - single JSON:
{
  "verdict": "ship" | "fix" | "redo",
  "must_fix": [
    {"file": "<path or 'multi'>", "issue": "<what's wrong>", "suggestion": "<concrete fix>"}
  ],
  "should_improve": [
    {"file": "...", "issue": "...", "suggestion": "..."}
  ],
  "summary": "1-3 sentences"
}

Default to verdict="fix" — only "ship" if the project is genuinely flawless. Use "redo" only if the architecture is fundamentally broken.
"""


FIX_SYSTEM = """You are fixing specific issues in a multi-file project. You receive the plan, the current files, and a list of issues that MUST be addressed.

Rules:
- Address EVERY issue listed. Don't skip any.
- Don't break what already works.
- Output the COMPLETE new content for each file you change. No diffs, no patches.
- Only include files that actually change.
- Maintain consistency with the plan and sibling files.

OUTPUT - single JSON, no prose, no fences:
{
  "files": [
    {"path": "...", "content": "<full updated file>"}
  ],
  "notes": "1-2 sentences on what you changed"
}
"""


QA_REVIEW_SYSTEM = """You are the QA Tester for an autonomous software-publishing pipeline. Every project ships to a public Pages URL where real visitors will try to use it. Your job is to judge: DOES THIS PROJECT ACTUALLY DELIVER THE INTERACTIVITY ITS PLAN PROMISED?

You receive:
- The plan (especially `ui_features` and `verification_criteria` — what the project promised)
- The source files
- The mechanical interaction-test result from headless Chromium: which controls were exercised and whether the page state actually changed in response to each one. Dead controls are listed by tag/type/label. The metric is: did `document.body.innerHTML.length`, displayed text, canvas pixel hash, or localStorage size change after triggering the control?

Your single most important question: would a curious visitor who opens this page find the controls actually DO something, or is it a static-looking mockup?

A button labelled "Run Simulation" that does nothing when clicked is WORSE than no button — it's deceptive. A slider that updates a displayed number but doesn't drive any visualization is half-built.

CRITERIA for verdict:

- **non_functional**: > 50% of controls don't change observable state, OR a core ui_feature from the plan is entirely missing (e.g., plan promises drag-and-drop visualization but only buttons exist), OR the canvas/main view never changes regardless of what the user does.

- **partially_usable**: 1–3 controls dead or pointless but the core experience still works. A "Save Configuration" button that fails silently while the rest of the simulation works is partially_usable.

- **shippable**: every promised feature actually does something visible or stateful. Sliders drive the visualization. Buttons cause real updates. Drag-and-drop targets accept and respond to drops. Login state actually persists.

OUTPUT — single JSON, no prose, no markdown fences:
{
  "verdict": "shippable" | "partially_usable" | "non_functional",
  "summary": "1-2 sentences of executive judgement",
  "dead_controls": [
    {"control": "<tag.type 'label'>", "expected": "<what it should do per plan>", "actual": "<what actually happened>", "fix": "<concrete code change>"}
  ],
  "missing_features": [
    {"feature": "<ui_feature from plan>", "why_missing": "<reason>", "fix": "<concrete code change>"}
  ],
  "directives_for_future": [
    "imperative instructions for future projects (architect must obey). 0-3 entries."
  ]
}

Rules:
- 'non_functional' requires that you name AT LEAST ONE specific dead control or missing feature with a code fix.
- Don't be pedantic about minor polish (a tooltip missing, a label slightly off). Focus on broken interaction.
- The mechanical interaction test in `browser.metrics.interaction.dead_controls` is your most important evidence — trust it. If it says 5 of 7 controls don't change state, the project is non_functional regardless of how nice it looks.
- If the plan promises a feature that the source code doesn't even attempt, call it out as `missing_features`, not just `dead_controls`.
"""


SECURITY_REVIEW_SYSTEM = """You are the Security Officer for an autonomous software-publishing pipeline. Every project is a small, self-contained, browser-runnable EDUCATIONAL DEMO published to GitHub Pages. There is no real backend, no real users, no real money, no real PII. Your job is to identify issues that could ACTUALLY HARM A VISITOR who opens the demo, not to enforce production-enterprise security policy on a static toy.

You receive: the plan, the final source files, and the browser-verify result. You return a structured security report. The pipeline will treat any issue with severity 'critical' or 'high' as a hard publish-blocker — those issues will be sent to a security-aware Fixer for remediation before another review is attempted.

CALIBRATION — read this carefully:

These projects are SAFE BY CONSTRUCTION in important ways:
- Static client-side only. No backend exists. There's no real database, no real authentication server, no real money flow.
- Hosted on GitHub Pages — same-origin only, no cross-origin secrets.
- All dependencies come from major CDNs (jsdelivr, unpkg, cdnjs) which are HTTPS and well-known.
- Visitors come knowing it's a demo. Disclosed as educational in README.

What this means for severity:
- "Mock auth without server-side verification" — INFO, not critical. The whole project IS the mock; that's the point of the demo.
- "Username stored in a JavaScript variable" — INFO. It's a single-page client demo, not a real session.
- "localStorage holding fake portfolio / fake game / fake-anything state" — INFO/LOW. Storing synthetic demo state is intended.
- "Bootstrap/Tailwind/Chart.js/etc. CDN included without SRI hash" — LOW at most. SRI is best-practice but not required for static demos; the entire jsdelivr ecosystem operates this way.
- "CSP not strict enough" — LOW unless there's an actual injection vector. A meta CSP is nice-to-have, not mandatory.
- "bcrypt hashSync used client-side" — INFO. It's a mock; nobody is registering real users.

What is STILL critical/high (real harm to visitor):
- Stored or reflected XSS via innerHTML, document.write, eval, new Function on UNSANITIZED user input that another visitor would see. (Example: a 'leave a comment' demo that renders the comment with innerHTML — if it persisted across visitors via localStorage, that's a real attack vector. If it's only the current user, it's self-XSS only — INFO at most.)
- Prototype pollution that other code paths actually consume.
- exfiltration of data to a third-party origin (fetch/XHR/beacon/img to non-CDN domains).
- Tracking, telemetry, fingerprinting code that isn't disclosed.
- Code that downloads and executes remote content at runtime (malware shape).
- Deceptive UX or README claims that materially mislead the visitor.
- Real PII or secrets accidentally hardcoded into the project (test API keys, real emails, tokens).
- Open redirects to attacker-controlled URLs.
- target="_blank" without rel="noopener noreferrer" leaking window.opener TO ATTACKER ORIGINS (not just internal anchors).

DEFAULT SEVERITY RULES:
- If a finding only affects the current user (self-XSS, their own localStorage), it's INFO.
- If a finding is a "best-practice deviation" with no demonstrated visitor harm, it's LOW.
- If you can't articulate a concrete attacker → visitor harm, do not exceed MEDIUM.
- 'critical' is reserved for actual-attacker-can-actually-hurt-a-visitor. Use it sparingly.

OUTPUT — single JSON, no prose, no markdown fences:
{
  "verdict": "secure" | "minor_concerns" | "publish_blocked",
  "summary": "1-2 sentence executive summary",
  "findings": [
    {
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "category": "xss" | "injection" | "dependency" | "ai_threat" | "privacy" | "deception" | "other",
      "file": "<path or 'multi'>",
      "issue": "what's wrong, specifically — and what visitor harm it causes",
      "suggestion": "concrete fix"
    }
  ],
  "directives_for_future": [
    "imperative instructions for future projects (architect must obey). 0-4 entries. Each one a single concrete thing."
  ]
}

Rules:
- If verdict is 'publish_blocked' there must be at least one critical/high with a clear visitor-harm path.
- If verdict is 'secure', findings can still include low/info items — those are advisory only.
- Be specific. 'CSP missing' is too vague; 'innerHTML used on .comment-text from localStorage which persists across page loads — could store XSS payload that fires on next visit' is right.
- Don't flag CDN URLs from jsdelivr/unpkg/cdnjs as 'untrusted' — those are the trusted choice for static demos.
- Don't escalate every best-practice deviation to critical. Educational demos earn pragmatic latitude.
"""


POLISH_SYSTEM = """The project works correctly. Now elevate it from "works" to "flawless". Make a visitor say "wow, this is polished."

Add or improve where appropriate:
- Visual polish: thoughtful color palette, gradients, subtle shadows/glows, smooth transitions, hover states, loading states, polished typography.
- More controls: parameter sliders with live feedback, presets, randomize, restart, pause/play, fullscreen, keyboard shortcuts.
- Better feedback: on-screen statistics, labels, tooltips, instructions for first-time visitors.
- Smarter defaults: opening state should be visually impressive immediately.
- Accessibility: ARIA labels, keyboard support, proper contrast, prefers-reduced-motion.
- Performance: requestAnimationFrame, object pooling for hot paths, debounced inputs.
- Resilience: handle resize, tab background, extreme parameter values.

CRITICAL: do not break what already works. Only improve.

OUTPUT - single JSON, no prose, no fences:
{
  "files": [{"path": "...", "content": "<full updated file>"}],
  "notes": "what you improved"
}
Only include files you actually changed.
"""


# ─────────────────────── Helpers ────────────────────────────────────────

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$")
HISTORY_WINDOW = 14


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise PipelineError(f"Model returned no JSON object. First 400 chars:\n{text[:400]}")
    return json.loads(text[s:e + 1])


def _call_role(client: OpenAI, role: str, system: str, user: str, *,
               max_tokens: int, temperature: float = 0.85,
               json_mode: bool = True) -> tuple[dict, dict[str, Any]]:
    """Call the LLM bound to a role. Returns (parsed_json, meta).
    Meta carries which model was actually used (post-fallback).

    JSON parse failures (often caused by truncated output when a smaller
    model hits max_tokens) are treated as model failures — the fallback
    chain is walked until a model produces valid JSON.
    """
    text, meta = roles.call_with_fallback(
        client, role,
        system=system, user=user,
        max_tokens=max_tokens, temperature=temperature,
        json_mode=json_mode,
        validator=_parse_json,   # truncated/malformed JSON → fall back
    )
    return _parse_json(text), meta


# Backwards-compatible shim — old code paths still call _call(model=...).
def _call(client: OpenAI, model: str, system: str, user: str, *,
          max_tokens: int, temperature: float = 0.85,
          json_mode: bool = True, attempts: int = 3) -> dict:
    """Legacy single-model call path, retained for any non-role-routed code."""
    for i in range(attempts):
        try:
            kwargs: dict[str, Any] = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            if resp.usage:
                log.info("[%s] tokens prompt=%d completion=%d",
                         model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
            return _parse_json(text)
        except PipelineError:
            raise
        except Exception as exc:
            if i == attempts - 1:
                raise
            backoff = 2 ** (i + 1)
            log.warning("Call failed (%s); retrying in %ds", exc, backoff)
            time.sleep(backoff)
    raise PipelineError("unreachable")


def _summarize_history(memory: dict) -> str:
    recent = memory.get("projects", [])[-HISTORY_WINDOW:]
    if not recent:
        return "No previous projects. This is day 1 — start at complexity 5 with real depth."
    lines = ["Recent project history (oldest → newest):"]
    for p in recent:
        concepts = ", ".join((p.get("concepts_demonstrated") or [])[:5])
        pat = p.get("pattern", "?")
        dom = p.get("domain", "?")
        lines.append(
            f"- {p.get('date')}  \"{p.get('name')}\"  "
            f"[{p.get('language')}, c={p.get('complexity_score')}, "
            f"pattern={pat}, domain={dom}]"
            f"  concepts: {concepts}"
        )
    cs = [p.get("complexity_score", 0) for p in recent]
    lines.append("")
    lines.append(f"Recent complexity: max={max(cs)}, avg={sum(cs)/len(cs):.1f}.")
    lines.append(f"Today's complexity_score MUST be >= {max(cs)+1} (open scale, no cap).")

    # Pattern + domain rotation - last 5
    last5 = memory.get("projects", [])[-5:]
    recent_patterns = [p.get("pattern") for p in last5 if p.get("pattern")]
    recent_domains = [p.get("domain") for p in last5 if p.get("domain")]
    if recent_patterns:
        lines.append(f"Patterns used in last 5 projects (you must NOT repeat): {', '.join(recent_patterns)}")
    if recent_domains:
        lines.append(f"Domains used in last 5 projects (you must NOT repeat): {', '.join(recent_domains)}")

    explored = memory.get("concepts_explored", [])
    if explored:
        lines.append("")
        lines.append(f"concepts_explored (your novel_concepts must NOT appear here):")
        lines.append(", ".join(explored[-50:]))
    return "\n".join(lines)


def _validate_plan(plan: dict, memory: dict) -> None:
    required = {
        "name", "description", "long_description", "language", "tech_stack",
        "complexity_score", "concepts_demonstrated", "novel_concepts",
        "advancement_axis", "is_web_project", "safety_notes",
        "architecture", "files", "ui_features", "verification_criteria",
        "pattern", "domain", "visual_identity",
    }
    missing = required - plan.keys()
    if missing:
        raise PipelineError(f"Plan missing required fields: {sorted(missing)}")
    if not NAME_RE.match(plan["name"]):
        raise PipelineError(f"Invalid plan name: {plan['name']!r}")
    if not plan.get("is_web_project"):
        raise PipelineError("All plans must be browser-runnable (is_web_project=true).")

    complexity = int(plan["complexity_score"])

    files = plan.get("files") or []
    # Scope minimum scales with complexity, but kept attainable for one-shot
    # implementation. Quality > sprawl.
    if complexity >= 13:
        min_files = 6
    elif complexity >= 10:
        min_files = 5
    else:
        min_files = 4
    if len(files) < min_files:
        raise PipelineError(
            f"Plan with complexity {complexity} needs >={min_files} files. Got {len(files)}."
        )

    # Recovery mode: when failures outnumber successes since the last ship,
    # the CEO is likely directing a scale-back. Relax the strict advancement +
    # rotation rules so the architect can propose something the model can
    # actually deliver. The CEO's directive text drives the *direction* of the
    # scale-back; the validator just stops blocking it.
    last_success_unix = max(
        (p.get("completed_at_unix", 0) for p in (memory.get("projects") or [])),
        default=0,
    )
    fails_since_last_ship = sum(
        1 for f in (memory.get("failed_builds") or [])
        if f.get("attempted_at_unix", 0) > last_success_unix
    )
    in_recovery = fails_since_last_ship >= 3
    if in_recovery:
        log.warning(
            "VALIDATOR recovery mode active: %d refused build(s) since last ship. "
            "Relaxing complexity floor + pattern/domain rotation so the CEO's "
            "scale-back directive can be obeyed.",
            fails_since_last_ship,
        )

    # Hard advancement gate — open-ended, no upper cap. Bypassed in recovery.
    recent = memory.get("projects", [])[-7:]
    if recent and not in_recovery:
        max_recent = max(p.get("complexity_score", 0) for p in recent)
        floor = max_recent + 1
        if complexity < floor:
            raise PipelineError(
                f"complexity_score={complexity} below required floor {floor} "
                f"(max recent={max_recent}). The scale is open-ended; surpass yesterday."
            )

    # Novel concepts gate — softer threshold in recovery (≥1 instead of ≥2)
    explored = set(memory.get("concepts_explored", []))
    novel = plan.get("novel_concepts") or []
    truly_novel = [c for c in novel if c not in explored]
    novel_min = 1 if in_recovery else 2
    if len(truly_novel) < novel_min:
        raise PipelineError(
            f"novel_concepts must include >={novel_min} entries NOT in "
            f"concepts_explored. You provided novel={novel}; truly novel={truly_novel}."
        )

    # Pattern rotation: must not match last 5 — bypassed in recovery so the
    # CEO can recommend a return to a proven pattern (visualizer/explorer/etc.)
    last5 = memory.get("projects", [])[-5:]
    recent_patterns = [p.get("pattern") for p in last5 if p.get("pattern")]
    recent_domains = [p.get("domain") for p in last5 if p.get("domain")]
    pattern = (plan.get("pattern") or "").strip().lower()
    domain = (plan.get("domain") or "").strip()
    if not pattern:
        raise PipelineError("`pattern` field is required (one project-genre token).")
    if not domain:
        raise PipelineError("`domain` field is required (one top-level discipline).")
    if not in_recovery:
        if pattern in [p.lower() for p in recent_patterns if p]:
            raise PipelineError(
                f"pattern={pattern!r} was used in the last 5 projects ({recent_patterns}). "
                "Pick a different genre."
            )
        if domain in recent_domains:
            raise PipelineError(
                f"domain={domain!r} was used in the last 5 projects ({recent_domains}). "
                "Pick a different discipline."
            )

    # File path safety + required artifacts + no-transpile rule
    forbidden_exts = {".ts", ".tsx", ".jsx", ".scss", ".less", ".vue",
                      ".svelte", ".coffee", ".pug", ".sass"}
    has_index = False
    has_readme = False
    for fs in files:
        path = fs.get("path", "")
        p = Path(path)
        if not path or p.is_absolute() or ".." in p.parts:
            raise PipelineError(f"Unsafe file path in plan: {path!r}")
        if p.suffix.lower() in forbidden_exts:
            raise PipelineError(
                f"File {path!r} requires a build step. GitHub Pages serves static "
                "files only. Use plain .js / .html / .css — never .ts, .jsx, .scss, etc."
            )
        if p.name.lower() == "index.html":
            has_index = True
        if p.name.lower() == "readme.md":
            has_readme = True
    if not has_index:
        raise PipelineError("Plan must include index.html (browser entry point).")
    # README will be auto-added if missing


def _ensure_readme_planned(plan: dict) -> None:
    if not any(Path(f["path"]).name.lower() == "readme.md" for f in plan["files"]):
        plan["files"].append({
            "path": "README.md",
            "role": "Project overview, how it works, controls, tech notes, safety statement.",
            "key_functions": [],
        })


# ─────────────────────── Stages ─────────────────────────────────────────

def stage_plan(client: OpenAI, memory: dict, ceo_directives: list[str] | None = None) -> dict:
    """
    Architect conference: two candidate models propose plans in parallel; the
    judge picks the strongest or synthesizes one. Returns the final plan with
    `__model__`, `__role__`, `__candidates_considered__` metadata attached.
    """
    history = _summarize_history(memory)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    base_user = f"Today is {today}. Produce today's design plan.\n\n{history}"
    if ceo_directives:
        base_user += "\n\nCEO DIRECTIVES (you must obey these):\n" + "\n".join(
            f"- {d}" for d in ceo_directives
        )

    candidate_roles = ["architect_candidate_a", "architect_candidate_b"]
    candidates: list[dict] = []
    last_err: str | None = None

    # Up to 2 rounds of soliciting candidates. Each round, every candidate role
    # gets a fresh attempt with whatever rejection reason last surfaced.
    for round_num in range(1, 3):
        log.info("ARCHITECT CONFERENCE round %d", round_num)
        for role in candidate_roles:
            try:
                user = base_user
                if last_err:
                    user += (
                        f"\n\nA prior candidate was rejected with this error — "
                        f"fix it and produce a valid plan:\n{last_err}"
                    )
                plan, meta = _call_role(client, role,
                                        PLAN_SYSTEM, user,
                                        max_tokens=4000)
                _validate_plan(plan, memory)
                _ensure_readme_planned(plan)
                plan["__model__"] = meta["model"]
                plan["__role__"] = role
                candidates.append(plan)
                log.info("✓ Candidate from %s (%s): %s | c=%d | files=%d",
                         role, meta["model"], plan["name"],
                         plan["complexity_score"], len(plan["files"]))
            except PipelineError as e:
                last_err = str(e)
                log.warning("✗ Candidate %s rejected: %s", role, last_err)
            except roles.AllModelsFailed as e:
                log.warning("✗ Candidate %s exhausted models: %s", role, e)
        if candidates:
            break

    if not candidates:
        raise PipelineError(
            f"Architect conference produced 0 valid candidates after {round_num} round(s). "
            f"Last error: {last_err}"
        )

    if len(candidates) == 1:
        log.info("Only one valid candidate; skipping judge.")
        return candidates[0]

    # Judge picks/synthesizes
    judge_input = json.dumps(
        [{k: v for k, v in c.items() if not k.startswith("__")} for c in candidates],
        indent=2,
    )[:18000]
    judge_user = (
        f"Today is {today}.\n\n{history}\n\n"
        f"Your engineering team produced {len(candidates)} candidate plans below. "
        "As Chief Architect, pick the strongest one OR synthesize a stronger plan "
        "by combining their best elements. Honor every constraint in your system "
        "prompt. Output ONE final plan in the same JSON schema. Do NOT add extra fields.\n\n"
        f"CANDIDATES:\n{judge_input}"
    )
    final, meta = _call_role(client, "architect_judge",
                             PLAN_SYSTEM, judge_user, max_tokens=4000)
    _validate_plan(final, memory)
    _ensure_readme_planned(final)
    final["__model__"] = meta["model"]
    final["__role__"] = "architect_judge"
    final["__candidates_considered__"] = len(candidates)
    final["__candidate_models__"] = [c["__model__"] for c in candidates]
    log.info("Judge (%s) chose plan: %s | c=%d | %d files | from %d candidates",
             meta["model"], final["name"], final["complexity_score"],
             len(final["files"]), len(candidates))
    return final


def stage_implement(client: OpenAI, plan: dict,
                    file_spec: dict, prior: dict[str, str]) -> tuple[str, str, dict]:
    """Engineer role writes one file. Returns (path, content, meta)."""
    plan_brief = {k: v for k, v in plan.items()
                  if k != "long_description" and not k.startswith("__")}
    prior_concat = "\n\n".join(
        f"=== {p} ===\n{c[:3000]}{'...[truncated]' if len(c) > 3000 else ''}"
        for p, c in prior.items()
    ) or "(none yet)"
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)[:8000]}\n\n"
        f"FILES ALREADY WRITTEN:\n{prior_concat}\n\n"
        f"NOW WRITE: {file_spec['path']}\n"
        f"ROLE: {file_spec.get('role', '')}\n"
        f"KEY FUNCTIONS: {file_spec.get('key_functions', [])}"
    )
    out, meta = _call_role(client, "engineer", IMPLEMENT_SYSTEM, user, max_tokens=4000)
    if "path" not in out or "content" not in out:
        raise PipelineError(f"Implement output missing fields: keys={list(out.keys())}")
    if not isinstance(out["content"], str) or len(out["content"]) < 30:
        raise PipelineError(f"File content too short for {file_spec['path']!r}: {len(out.get('content', ''))} chars")
    return file_spec["path"], out["content"], meta


def stage_critique(client: OpenAI, plan: dict,
                   files: dict[str, str], browser_result: dict | None) -> dict:
    """
    Critique conference: two reviewer models examine the project independently;
    their must_fix lists are merged (deduped by issue text); the most-pessimistic
    verdict wins. Each reviewer's identity is preserved in `_reviews` for audit.
    """
    plan_brief = {k: plan[k] for k in
                  ("name", "description", "verification_criteria", "ui_features",
                   "concepts_demonstrated", "complexity_score") if k in plan}
    files_concat = _concat_files(files, budget=22000)
    browser_summary = json.dumps(browser_result or {}, indent=2)[:3500]
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"FILES:\n{files_concat}\n\n"
        f"BROWSER VERIFY (real headless Chrome):\n{browser_summary}"
    )

    reports: list[dict] = []
    for role in ("reviewer_a", "reviewer_b"):
        try:
            report, meta = _call_role(client, role, CRITIQUE_SYSTEM, user, max_tokens=2500)
            report["__model__"] = meta["model"]
            report["__role__"] = role
            reports.append(report)
            log.info("Reviewer %s (%s): verdict=%s, must_fix=%d",
                     role, meta["model"],
                     report.get("verdict"),
                     len(report.get("must_fix") or []))
        except (PipelineError, roles.AllModelsFailed) as e:
            log.warning("Reviewer %s failed: %s", role, e)

    if not reports:
        raise PipelineError("Critique conference: every reviewer failed.")

    # Merge must_fix lists (dedup by first 60 chars of issue text)
    merged_must_fix: list[dict] = []
    seen: set[str] = set()
    for r in reports:
        for item in (r.get("must_fix") or []):
            if not isinstance(item, dict):
                continue
            key = (item.get("issue", "")[:60]).lower().strip()
            if key and key not in seen:
                seen.add(key)
                # Tag with which reviewer raised it
                item = {**item, "raised_by": r.get("__model__", "?")}
                merged_must_fix.append(item)

    # Most-pessimistic verdict wins
    verdicts = [r.get("verdict", "fix") for r in reports]
    if "redo" in verdicts:
        verdict = "redo"
    elif "fix" in verdicts:
        verdict = "fix"
    else:
        verdict = "ship"

    summary = " || ".join(
        f"[{r.get('__model__','?')}] {r.get('summary','')[:200]}"
        for r in reports
    )

    return {
        "verdict": verdict,
        "must_fix": merged_must_fix,
        "should_improve": [s for r in reports for s in (r.get("should_improve") or [])],
        "summary": summary[:800],
        "_reviews": [
            {
                "model": r.get("__model__"),
                "verdict": r.get("verdict"),
                "n_must_fix": len(r.get("must_fix") or []),
            }
            for r in reports
        ],
    }


def stage_fix(client: OpenAI, plan: dict,
              files: dict[str, str], issues: list[str]) -> dict[str, str]:
    """Fixer role applies a list of issues. Returns {path: content} of changes.

    Output budget is the bottleneck — when too many files need updating in one
    response, gpt-4o-mini truncates JSON. To prevent that, we cap the fix
    prompt files at 14k chars and request 6000 max output tokens, which gives
    the fixer real headroom for full file rewrites.
    """
    plan_brief = {k: plan[k] for k in
                  ("name", "verification_criteria", "ui_features") if k in plan}
    files_concat = _concat_files(files, budget=14000)  # was 22000 — output truncation
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"CURRENT FILES:\n{files_concat}\n\n"
        f"ISSUES TO FIX (every one of these must be addressed):\n"
        + "\n".join(f"- {issue}" for issue in issues)
        + "\n\nIMPORTANT: only include files in your response that ACTUALLY need to change. "
          "If a file doesn't need fixes, omit it. Do not echo unchanged files. Keep your "
          "response under 6000 tokens."
    )
    out, meta = _call_role(client, "fixer", FIX_SYSTEM, user, max_tokens=6000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("Fixer (%s) produced %d update(s): %s",
             meta["model"], len(updates), list(updates.keys()))
    return updates


def stage_qa_review(client: OpenAI, plan: dict,
                    files: dict[str, str],
                    browser_result: dict | None) -> dict:
    """
    Per-project QA gate. Returns a structured report:
      { verdict, summary, dead_controls: [...], missing_features: [...] }
    Verdicts:
      - 'shippable'         → ship
      - 'partially_usable'  → ship, but log issues
      - 'non_functional'    → block; feed dead-control list to qa_fixer
    """
    plan_brief = {k: plan[k] for k in
                  ("name", "description", "ui_features", "verification_criteria",
                   "concepts_demonstrated") if k in plan}
    files_concat = _concat_files(files, budget=14000)
    metrics = (browser_result or {}).get("metrics") or {}
    interaction = metrics.get("interaction") or {}
    interaction_summary = json.dumps(interaction, indent=2)[:2500]
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"INTERACTION TEST (headless Chromium drove each control):\n{interaction_summary}\n\n"
        f"FINAL FILES:\n{files_concat}\n\n"
        "Evaluate usability. Return a single JSON object per the schema."
    )
    out, meta = _call_role(client, "qa_tester",
                           QA_REVIEW_SYSTEM, user, max_tokens=2500)
    out["__model__"] = meta["model"]
    dead_count = len(out.get("dead_controls") or [])
    missing_count = len(out.get("missing_features") or [])
    log.info(
        "QA review (%s): verdict=%s, dead=%d, missing=%d. %s",
        meta["model"], out.get("verdict"), dead_count, missing_count,
        out.get("summary", "")[:200],
    )
    return out


def stage_qa_fix(client: OpenAI, plan: dict,
                 files: dict[str, str], issues: list[str]) -> dict[str, str]:
    """QA-aware Fixer. Routes to qa_fixer (gpt-4o)."""
    plan_brief = {k: plan[k] for k in
                  ("name", "ui_features", "verification_criteria") if k in plan}
    files_concat = _concat_files(files, budget=14000)
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"CURRENT FILES:\n{files_concat}\n\n"
        f"USABILITY ISSUES TO FIX (each is a hard publish-blocker — wire the "
        f"controls so they actually change page state):\n"
        + "\n".join(f"- {i}" for i in issues)
        + "\n\nGuidance:\n"
          "- Every button MUST have an event listener that mutates state, "
          "redraws the canvas, updates DOM text, or modifies localStorage.\n"
          "- Sliders/range inputs MUST trigger 'input' or 'change' handlers "
          "that visibly update the simulation/visualization.\n"
          "- Drag-and-drop targets MUST handle dragover (preventDefault) and "
          "drop events with visible state changes.\n"
          "- If a feature in the plan's ui_features list isn't implemented, "
          "build it now.\n\n"
        "Output FULL updated files (only those that change). Same JSON schema "
        "as the regular Fixer."
    )
    out, meta = _call_role(client, "qa_fixer", FIX_SYSTEM, user, max_tokens=6000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("QA fixer (%s) produced %d update(s): %s",
             meta["model"], len(updates), list(updates.keys()))
    return updates


def stage_security_review(client: OpenAI, plan: dict,
                          files: dict[str, str],
                          browser_result: dict | None) -> dict:
    """
    Per-project security gate. Returns a structured report:
      { verdict, summary, findings: [...], directives_for_future: [...] }
    Verdicts:
      - 'secure'           → ship
      - 'minor_concerns'   → ship, but log findings
      - 'publish_blocked'  → DO NOT ship; feed critical/high to fixer
    """
    plan_brief = {k: plan[k] for k in
                  ("name", "description", "tech_stack", "ui_features",
                   "concepts_demonstrated", "complexity_score") if k in plan}
    files_concat = _concat_files(files, budget=18000)
    browser_summary = json.dumps(browser_result or {}, indent=2)[:2500]
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"FINAL FILES:\n{files_concat}\n\n"
        f"BROWSER VERIFY METRICS:\n{browser_summary}\n\n"
        "Conduct the security review now. Return a single JSON object per the schema."
    )
    out, meta = _call_role(client, "security_officer",
                           SECURITY_REVIEW_SYSTEM, user, max_tokens=2500)
    out["__model__"] = meta["model"]
    findings = out.get("findings", []) or []
    blocking = [
        f for f in findings
        if isinstance(f, dict) and f.get("severity") in ("critical", "high")
    ]
    log.info(
        "Security review (%s): verdict=%s, findings=%d (blocking=%d). %s",
        meta["model"], out.get("verdict"), len(findings), len(blocking),
        out.get("summary", "")[:200],
    )
    for f in blocking:
        log.warning(
            "  [%s] [%s] %s -- suggestion: %s",
            f.get("severity", "?").upper(),
            f.get("category", "?"),
            f.get("issue", "")[:160],
            f.get("suggestion", "")[:160],
        )
    return out


def stage_security_fix(client: OpenAI, plan: dict,
                       files: dict[str, str], issues: list[str]) -> dict[str, str]:
    """
    Security-specific Fixer. Routes to the `security_fixer` role (gpt-4o by
    default — more capable than the regular gpt-4o-mini fixer for the kind of
    careful rewrites XSS and prototype-pollution remediation requires).

    Same input/output shape as stage_fix but with stronger system prompt
    biased toward defensive coding patterns.
    """
    plan_brief = {k: plan[k] for k in
                  ("name", "verification_criteria", "ui_features", "tech_stack")
                  if k in plan}
    files_concat = _concat_files(files, budget=14000)
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"CURRENT FILES:\n{files_concat}\n\n"
        f"SECURITY FINDINGS TO REMEDIATE (every one is a hard publish-blocker):\n"
        + "\n".join(f"- {issue}" for issue in issues)
        + "\n\nGuidance for safe rewrites:\n"
          "- Replace innerHTML with textContent or use document.createElement + setAttribute. \n"
          "- For DOM injection from user input, use the safelist whitelist approach.\n"
          "- For canvas fillText with user input, you don't need to sanitize for XSS, but make "
          "sure user input doesn't escape into a DOM-ish context elsewhere.\n"
          "- For localStorage/sessionStorage holding sensitive-looking keys, document why it's "
          "safe (synthetic data only) in a code comment, OR remove the storage and keep state "
          "in memory.\n"
          "- For drag-and-drop: use dataTransfer.getData('text/plain') and validate before use; "
          "never insert dropped text via innerHTML.\n"
          "- Add <meta http-equiv='Content-Security-Policy'> with default-src 'self' plus "
          "explicit allowlist of any CDNs you load.\n\n"
        "Output the FULL corrected files (only those that change). Same JSON schema as the "
        "regular Fixer."
    )
    out, meta = _call_role(client, "security_fixer", FIX_SYSTEM, user, max_tokens=6000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("Security-fixer (%s) produced %d update(s): %s",
             meta["model"], len(updates), list(updates.keys()))
    return updates


def stage_polish(client: OpenAI, plan: dict,
                 files: dict[str, str]) -> dict[str, str]:
    """Polisher role elevates UX. Returns {path: content} of changes.

    Same output-budget concerns as the fixer — capped at 14k input chars and
    6000 output tokens so we don't truncate.
    """
    plan_brief = {k: plan[k] for k in
                  ("name", "description", "ui_features") if k in plan}
    files_concat = _concat_files(files, budget=14000)
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"WORKING FILES:\n{files_concat}\n\n"
        "IMPORTANT: only include files in your response that you actually polished. "
        "If a file doesn't need polish, omit it. Keep your response under 6000 tokens."
    )
    out, meta = _call_role(client, "polisher", POLISH_SYSTEM, user, max_tokens=6000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("Polisher (%s) produced %d update(s): %s",
             meta["model"], len(updates), list(updates.keys()))
    return updates


def _concat_files(files: dict[str, str], budget: int) -> str:
    parts: list[str] = []
    used = 0
    for path, content in files.items():
        block = f"=== {path} ===\n{content}\n"
        if used + len(block) > budget and parts:
            parts.append(f"=== ... {len(files) - len(parts)} more file(s) truncated ===")
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)
