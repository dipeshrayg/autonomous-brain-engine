"""
pipeline.py - Multi-stage LLM code-generation pipeline.

Stages:
    1. PLAN       - architect the project at the design level (no code yet).
    2. IMPLEMENT  - per-file generation (one call per file, no 4K-token squeeze).
    3. CRITIQUE   - senior engineer pre-ship review (combined with browser verify).
    4. FIX        - apply specific issues, returning full updated files only.
    5. POLISH     - elevate from "works" to "flawless" (visuals, controls, edge cases).

The orchestrator wraps stages 3+4 in a quality loop until the project is clean
or MAX_QUALITY_CYCLES is exhausted. Hard advancement constraints are enforced
in `_validate_plan` so a stale, low-complexity plan never reaches code-gen.
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

log = logging.getLogger("brain.pipeline")


class PipelineError(RuntimeError):
    pass


# ─────────────────────── Prompts ────────────────────────────────────────

PLAN_SYSTEM = """You are the Chief Architect of an autonomous, daily software-creation pipeline. Today you produce a DESIGN PLAN for a new project — the plan only, no code. A separate stage will turn the plan into code.

ABSOLUTE CONSTRAINTS - non-negotiable:
1. Comply strictly with GitHub TOS / Acceptable Use. No active malware, no exfiltration, no exploits against systems without consent. Security topics are educational/diagnostic only.
2. The project MUST run in any modern browser by serving a single index.html via GitHub Pages — no install, no build step. Allowed runtimes: HTML+CSS+JavaScript, optionally WebGL/WebGPU/WASM/Web Audio.
3. HARD ADVANCEMENT (the most important rule):
   - complexity_score must be at least max(recent complexity scores) + 1, capped at 10. If recent max is 8, today is 9.
   - novel_concepts must contain AT LEAST TWO concepts not present in concepts_explored.
   - tech_stack must include at least one library/technique no previous project has used.
   - advancement_axis must explicitly state how today is more advanced (deeper algorithm, richer interaction, larger architecture, novel domain, etc.).
4. SUBSTANTIVE SCOPE:
   - At least 4 source files in addition to README.md (so 5 total minimum). Examples: index.html, app.js, engine.js, ui.js, style.css.
   - Real depth: multiple algorithms or systems, real-time interactivity, polished UI with multiple controls (sliders, presets, pause/resume, randomize, etc.), edge case handling.
   - Visualizations must be informative and dynamic — not static dots, not a single line.
5. UI REQUIREMENTS the verifier will check mechanically:
   - At least 3 interactive controls (buttons, sliders, selects).
   - <meta name="viewport">.
   - The canvas (if any) must actually render content — the loop must be running and drawing on first frame.

OUTPUT — single JSON object, no prose, no markdown fences, schema:
{
  "name": "kebab-case (3-60 chars, ascii)",
  "description": "≤200 chars",
  "long_description": "2-4 paragraphs for README",
  "language": "primary language",
  "tech_stack": [list of specific libs/APIs],
  "complexity_score": int 1-10,
  "concepts_demonstrated": [list],
  "novel_concepts": [list of concepts NOT in concepts_explored],
  "advancement_axis": "explicit explanation of how this exceeds recent projects",
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
- For HTML: <!DOCTYPE html>, charset, viewport, semantic structure, all referenced scripts/styles must exist in sibling files.
- For JS: handle DOMContentLoaded properly, no top-level statements that touch the DOM before it's ready, handle resize, handle edge cases, no unhandled promise rejections.
- For CSS: responsive, accessible, polished — use modern selectors, custom properties, prefers-color-scheme.
- Pin any CDN versions explicitly (e.g., d3@7.8.5).
- The result must be runnable as-is when served statically.

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


def _call(client: OpenAI, model: str, system: str, user: str, *,
          max_tokens: int, temperature: float = 0.85,
          json_mode: bool = True, attempts: int = 3) -> dict:
    """LLM call with JSON output and bounded retries on transient errors."""
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
            raise  # parse errors don't get retried — model needs new instructions
        except Exception as exc:  # network / rate / 5xx
            if i == attempts - 1:
                raise
            backoff = 2 ** (i + 1)
            log.warning("Call failed (%s); retrying in %ds", exc, backoff)
            time.sleep(backoff)
    raise PipelineError("unreachable")


def _summarize_history(memory: dict) -> str:
    recent = memory.get("projects", [])[-HISTORY_WINDOW:]
    if not recent:
        return "No previous projects. This is day 1 — start at complexity 4 with real depth."
    lines = ["Recent project history (oldest → newest):"]
    for p in recent:
        concepts = ", ".join((p.get("concepts_demonstrated") or [])[:5])
        lines.append(
            f"- {p.get('date')}  \"{p.get('name')}\"  "
            f"[{p.get('language')}, complexity {p.get('complexity_score')}]"
            f"  concepts: {concepts}"
        )
    cs = [p.get("complexity_score", 0) for p in recent]
    lines.append("")
    lines.append(f"Recent complexity: max={max(cs)}, avg={sum(cs)/len(cs):.1f}.")
    lines.append(f"Today's complexity_score MUST be >= {min(max(cs)+1, 10)}.")
    explored = memory.get("concepts_explored", [])
    if explored:
        lines.append("")
        lines.append(f"concepts_explored (your novel_concepts must NOT appear here):")
        lines.append(", ".join(explored))
    return "\n".join(lines)


def _validate_plan(plan: dict, memory: dict) -> None:
    required = {
        "name", "description", "long_description", "language", "tech_stack",
        "complexity_score", "concepts_demonstrated", "novel_concepts",
        "advancement_axis", "is_web_project", "safety_notes",
        "architecture", "files", "ui_features", "verification_criteria",
    }
    missing = required - plan.keys()
    if missing:
        raise PipelineError(f"Plan missing required fields: {sorted(missing)}")
    if not NAME_RE.match(plan["name"]):
        raise PipelineError(f"Invalid plan name: {plan['name']!r}")
    if not plan.get("is_web_project"):
        raise PipelineError("All plans must be browser-runnable (is_web_project=true).")
    files = plan.get("files") or []
    if len(files) < 4:
        raise PipelineError(f"Plan needs >=4 files (excluding README in concept). Got {len(files)}.")

    # Hard advancement gates
    recent = memory.get("projects", [])[-7:]
    if recent:
        max_recent = max(p.get("complexity_score", 0) for p in recent)
        floor = min(max_recent + 1, 10)
        if int(plan["complexity_score"]) < floor:
            raise PipelineError(
                f"complexity_score={plan['complexity_score']} below required floor {floor} "
                f"(max recent={max_recent})."
            )
    explored = set(memory.get("concepts_explored", []))
    novel = plan.get("novel_concepts") or []
    truly_novel = [c for c in novel if c not in explored]
    if len(truly_novel) < 2:
        raise PipelineError(
            f"novel_concepts must include >=2 entries NOT in concepts_explored. "
            f"You provided novel={novel}; truly novel={truly_novel}."
        )

    # File path safety + required artifacts
    has_index = False
    has_readme = False
    for fs in files:
        path = fs.get("path", "")
        p = Path(path)
        if not path or p.is_absolute() or ".." in p.parts:
            raise PipelineError(f"Unsafe file path in plan: {path!r}")
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

def stage_plan(client: OpenAI, model: str, memory: dict) -> dict:
    history = _summarize_history(memory)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user = f"Today is {today}. Produce today's design plan.\n\n{history}"

    last_err: str | None = None
    for attempt in range(1, 4):
        log.info("PLAN attempt %d", attempt)
        retry_note = (
            f"\n\nThe previous plan was REJECTED with this error — fix it and retry:\n{last_err}"
            if last_err else ""
        )
        plan = _call(client, model, PLAN_SYSTEM, user + retry_note, max_tokens=4000)
        try:
            _validate_plan(plan, memory)
            _ensure_readme_planned(plan)
            log.info("Plan OK: %s | complexity %d | %d files | novel: %s",
                     plan["name"], plan["complexity_score"], len(plan["files"]),
                     plan.get("novel_concepts"))
            return plan
        except PipelineError as e:
            last_err = str(e)
            log.warning("Plan rejected: %s", last_err)
    raise PipelineError(f"Plan stage failed after 3 tries. Last error: {last_err}")


def stage_implement(client: OpenAI, model: str, plan: dict,
                    file_spec: dict, prior: dict[str, str]) -> tuple[str, str]:
    plan_brief = {k: v for k, v in plan.items() if k != "long_description"}
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
    out = _call(client, model, IMPLEMENT_SYSTEM, user, max_tokens=4000)
    if "path" not in out or "content" not in out:
        raise PipelineError(f"Implement output missing fields: keys={list(out.keys())}")
    if not isinstance(out["content"], str) or len(out["content"]) < 30:
        raise PipelineError(f"File content too short for {file_spec['path']!r}: {len(out.get('content', ''))} chars")
    return file_spec["path"], out["content"]


def stage_critique(client: OpenAI, model: str, plan: dict,
                   files: dict[str, str], browser_result: dict | None) -> dict:
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
    return _call(client, model, CRITIQUE_SYSTEM, user, max_tokens=2500)


def stage_fix(client: OpenAI, model: str, plan: dict,
              files: dict[str, str], issues: list[str]) -> dict[str, str]:
    plan_brief = {k: plan[k] for k in
                  ("name", "verification_criteria", "ui_features") if k in plan}
    files_concat = _concat_files(files, budget=22000)
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"CURRENT FILES:\n{files_concat}\n\n"
        f"ISSUES TO FIX (every one of these must be addressed):\n"
        + "\n".join(f"- {issue}" for issue in issues)
    )
    out = _call(client, model, FIX_SYSTEM, user, max_tokens=4000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("Fix produced %d file update(s): %s", len(updates), list(updates.keys()))
    return updates


def stage_polish(client: OpenAI, model: str, plan: dict,
                 files: dict[str, str]) -> dict[str, str]:
    plan_brief = {k: plan[k] for k in
                  ("name", "description", "ui_features") if k in plan}
    files_concat = _concat_files(files, budget=22000)
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"WORKING FILES:\n{files_concat}"
    )
    out = _call(client, model, POLISH_SYSTEM, user, max_tokens=4000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("Polish produced %d file update(s): %s", len(updates), list(updates.keys()))
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
