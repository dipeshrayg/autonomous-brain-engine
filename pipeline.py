"""
pipeline.py — Project Evolution multi-stage pipeline.

Stages:
    1. PLAN        Architect Conference (2 candidates + Judge with predictability filter)
    2. IMPLEMENT   Engineer per-file generation
    3. CRITIQUE    Reviewer Conference (parallel, results merged)
    4. FIX         Iterative repair
    5. POLISH      Final UX pass with rollback safety
    6. QA          Visual + state-sync test (mechanical) + LLM Tester verdict

Removed in Project Evolution: SECURITY stage entirely. Trade-off the user
explicitly accepted: less pre-publish review, fewer false-positive blocks,
more domain freedom.

The pipeline supports multiple project types now:
    - web_interactive   HTML/JS/Canvas in browser (default, uses Playwright)
    - web_3d            Three.js / WebGL in browser (uses Playwright)
    - python_tool       Python script runnable via Codespaces (no Pages)
    - document          Markdown + asset files (research, business, schematic)
    - generative_art    Static visual output (web or document hybrid)
    - game_web          Browser game with rules + state (uses Playwright)
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


PROJECT_TYPES = (
    "web_interactive",
    "web_3d",
    "python_tool",
    "document",
    "generative_art",
    "game_web",
)

# Complexity ceilings per type — once a type's max shipped complexity reaches
# its ceiling, the system MUST switch to a different type.  The ceiling
# represents the practical depth limit: beyond it, the type can't express
# more sophistication without a language/paradigm shift.
TYPE_COMPLEXITY_CEILING: dict[str, int] = {
    "document":        35,   # markdown + styled HTML showcase can be rich
    "generative_art":  40,   # visual algorithms, shaders, fractals — deep
    "web_interactive": 40,   # vanilla JS/HTML with Canvas can go far
    "game_web":        45,   # browser game with AI, procedural gen
    "web_3d":          45,   # Three.js / WebGL is deep
    "python_tool":     60,   # Python is versatile, highest ceiling
}

# Tier ordering: when current type is maxed, prefer the next tier up.
TYPE_ESCALATION_ORDER = [
    "document",           # easiest
    "generative_art",     # visual + code
    "web_interactive",    # interactive browser
    "game_web",           # stateful browser
    "web_3d",             # 3D browser
    "python_tool",        # highest ceiling
]


# ─────────────────────── Prompts ────────────────────────────────────────

PLAN_SYSTEM = """You are a CANDIDATE Architect proposing a project plan for an autonomous software-creation pipeline. Project Evolution mandate: be unpredictable, push domains, refuse derivative ideas.

You receive: history of recent projects, recent refused builds, CEO directives, CSO directives. The CEO and CSO are deliberately allowed to disagree. Find the strongest synthesis you can.

PROJECT TYPES — pick ONE that genuinely fits the idea:

    web_interactive   HTML+JS+Canvas demo in a browser. The default; pick something else if you can.
    web_3d            Three.js / WebGL scene loaded from CDN, runs in browser.
    python_tool       Python program. User runs it in GitHub Codespaces or locally.
                      No Pages. Examples: cyber-forensic utility, ML experiment,
                      simulation engine, data-pipeline demo.
    document          Markdown + asset files. Research article, business proposal,
                      product design schematic, ASCII-diagrammed system architecture.
                      The "deliverable" is reading material, not running code.
    generative_art    Hybrid: produces visual output (web canvas OR static images).
    game_web          Browser game — rules, state, win condition, multiple screens.

ABSOLUTE CONSTRAINTS:
1. Comply with GitHub TOS. No active malware, no exploits against systems without consent. Educational / diagnostic / synthetic demos only.
2. EVERY project — regardless of type — MUST include an index.html at repo root that is viewable in GitHub Pages. This is the user's ONLY way to experience the project from the dashboard. The index.html must be a VISUAL SHOWCASE:
   - web_interactive / web_3d / game_web / generative_art: index.html IS the project itself.
   - python_tool: index.html is a RICH VISUAL SHOWCASE page. It must show: project title + description, architecture diagram (use HTML/CSS/SVG, not images), sample outputs (embedded SVG, ASCII art rendered in <pre>, or generated visualizations), the core algorithm explained visually with diagrams/animations, a live interactive demo element if possible (e.g. a JS port of the core algorithm), and a "Run in Codespaces" button. The index.html should make the viewer say "wow" even without running Python.
   - document: index.html is a BEAUTIFULLY STYLED reader page. Render the document content as a polished web page with typography, diagrams, table of contents, and visual flair — NOT just raw markdown. Make it look like a published article on Medium or a research paper.
3. Python tools: must ALSO run with `python <entry>` in a Codespaces dev container; declare deps in requirements.txt. The Python code is the real project; index.html is the showcase.
4. ABSOLUTELY NO COMPILED-LANGUAGE FILES that require transpilation (.ts, .jsx, .scss, .vue, etc.). Plain languages only.
5. NO BACKEND SERVERS, WebSockets, or localhost connections. Everything web-facing runs as STATIC files on GitHub Pages — no Node.js server, no Express, no WebSocket server. Multiplayer/cooperative features must use local-only simulation (AI opponents, hot-seat multiplayer, or single-player with simulated cooperation).

TYPE DIVERSITY — you MUST NOT repeat the same project_type as the previous build. The system enforces type rotation. Read the TYPE DIVERSITY REPORT in the user prompt to see which types are underrepresented, which are maxed out, and which is recommended. Once a type's max shipped complexity reaches its ceiling, that type is LOCKED and you must escalate to a higher-ceiling type. The ceilings are: document=20, generative_art=25, web_interactive=30, game_web=35, web_3d=35, python_tool=50.

PATTERN ROTATION — your `pattern` should differ from the most recent shipped projects unless you're in recovery mode (CEO directive will say so).

PROVEN-WEAK PATTERNS — these have failed repeatedly recently. Avoid unless you have a fundamentally new angle:
- "workspace" pattern (multi-pane drag-drop persistence demos)
- "simulator" with multiple disconnected subsystems
- "storytelling" / "narrative" demos with save/load buttons
- "dashboard" with charts you don't actually drive

INTERACTION-LOGIC RIGOR (very important — recent failures have been here):
- For every interactive control you list in `ui_features`, you must also describe what state it changes and how the visual representation reflects that change.
- For drag-drop: source ID + target zone + how the drop event mutates state + how the canvas re-renders.
- For randomize / reset / regenerate: what specific elements get reset, what stays.
- For node graphs: how a click maps coordinates to a state index AND how the visual highlight follows.
- If you can't describe the state-sync, the feature is too vague — drop it or refine it.

OUTPUT — single JSON, no prose, no markdown fences:
{
  "name": "kebab-case (3-60 chars, ascii)",
  "description": "<=200 chars",
  "long_description": "2-4 paragraphs",
  "project_type": "<one of: web_interactive | web_3d | python_tool | document | generative_art | game_web>",
  "language": "primary language",
  "tech_stack": [list],
  "complexity_score": int (open scale, 1+),
  "concepts_demonstrated": [list],
  "novel_concepts": [list of concepts NOT in concepts_explored],
  "advancement_axis": "what makes this NOT predictable",
  "pattern": "kebab-case genre token",
  "domain": "top-level discipline",
  "visual_identity": "color palette + typography + layout personality",
  "is_web_project": true|false,
  "safety_notes": "...",
  "architecture": {
    "overview": "...",
    "data_flow": "...",
    "key_algorithms": ["alg: brief"]
  },
  "files": [
    {"path": "relative/path", "role": "what it does", "key_functions": [list]}
  ],
  "ui_features": [
    {"control": "<tag.type 'label'>", "state_change": "what it mutates", "visual_response": "what the user sees change"}
  ],
  "verification_criteria": ["specific things that must work after the page loads / script runs"]
}
"""


JUDGE_SYSTEM = """You are the JUDGE of an autonomous architect conference. Your job has ONE metric:

    IS THIS PROJECT PREDICTABLE?

If yes, REJECT. If no, accept and synthesize.

Predictable means: this is what a competent-but-unimaginative LLM would propose for a "make me a daily project" prompt. A web-app visualizer / dashboard / explorer with sliders and a canvas IS predictable. An OpenSCAD parametric mechanical part is NOT predictable. A Python forensic tool IS NOT predictable. A markdown research article on consensus protocols IS NOT predictable.

You receive 1-3 candidate plans. For each, ask:
- Does this break out of the "web-app visualizer" mould?
- Is the project_type non-default?
- Does it use techniques the system has not used recently?
- Would a senior engineer say "huh, that's a strange one" or "yet another canvas demo"?

Return ONE final plan in the exact same JSON schema as the candidates. You may:
1. Pick the strongest unpredictable candidate verbatim
2. Synthesize a stronger plan combining elements
3. Reject all candidates if all are too safe — in that case, propose your OWN plan, more unpredictable, in the same schema, with `name` and `pattern` and `project_type` you actually believe in.

Honor the CEO and CSO directives the candidates were given. The pattern + domain rotation rules and complexity floor are enforced by a downstream validator — your job is the predictability bar.
"""


IMPLEMENT_SYSTEM = """You are implementing ONE file of a multi-file project. You receive the plan, sibling files already written, and the file you must produce.

RULES:
- Production-quality. NO TODOs, placeholders, stubs.
- Honor the plan's project_type:
  - web_interactive / web_3d / generative_art / game_web: HTML+CSS+JS at repo root, no build step. Plain .js / .html / .css ONLY (no .ts, .jsx, .scss, etc.). Prefer classic <script src="...">; modules require careful path handling. CDN libraries pinned to explicit version.
  - python_tool: Python files + requirements.txt for the core tool, BUT ALSO an index.html that is a rich visual showcase. The index.html should: have a polished dark-themed design, show the project architecture with SVG/CSS diagrams, demonstrate sample outputs visually, explain the core algorithm with interactive elements or animations in plain JS, and include a "Run in Codespaces" button. This page IS the user's first experience — make it impressive.
  - document: The primary content goes in markdown files, BUT index.html must be a beautiful styled reader page that presents the content as a polished article with proper typography, table of contents, diagrams, and visual identity. Think: a published article on a professional blog, not raw markdown.
- Every interactive control your sibling files reference MUST have its event listener wired in this file (if this is the file that owns it). Buttons that look interactive but do nothing are the worst possible bug — do not produce them.
- For canvas + state-bearing UIs: the click handler must compute coordinates the SAME way the render code uses them. State + visual must stay in sync.
- For randomize / reset: enumerate exactly which DOM elements + state slots are touched.
- For drag-drop: dragstart sets dataTransfer; dragover preventDefault; drop reads dataTransfer + mutates state + triggers re-render.
- CANVAS RENDERING (critical — blank canvas is the #1 failure mode):
  - The canvas MUST have explicit width/height attributes: <canvas id="game" width="800" height="600"></canvas>
  - Drawing code MUST run after DOMContentLoaded or be in a <script> tag at the END of <body>.
  - An animation loop (requestAnimationFrame) MUST be started immediately — don't wait for user interaction.
  - Draw SOMETHING visible on first frame (background color, initial state) so the canvas is never blank.
- SCRIPT LOADING ORDER (critical — ReferenceError is the #2 failure mode):
  - If file A defines class Foo and file B uses Foo, then <script src="A.js"></script> MUST come BEFORE <script src="B.js"></script> in index.html.
  - Prefer putting ALL game logic in ONE file (e.g. game.js) to avoid load-order bugs. Only split into multiple files if absolutely necessary.
  - NEVER use ES modules (import/export) — use classic <script> tags with global scope.
- INPUT WIRING (critical — dead number/text inputs are the #3 failure mode):
  - Every <input type="number">, <input type="text">, and <textarea> MUST have an oninput or onchange event listener that reads .value and triggers a state update + re-render.
  - Never let a user-editable field sit unwired. If the field sets grid size, call resizeGrid() in the listener. If it sets a parameter, re-run the simulation.
  - Pattern: input.addEventListener('input', e => { state.param = +e.target.value; redraw(); });
- WEB_3D CONTROLS (critical — ALL Three.js/WebGL controls must pass the interaction test):
  - Every slider/button MUST call renderer.render(scene, camera) or ensure the animation RAF loop is already running continuously BEFORE any user interaction.
  - MANDATORY DOM VALUE DISPLAYS: For EVERY slider and numeric control, add a paired <span> or <div> that shows the current value and updates on each input event. Example:
      <label>Speed: <span id="speed-val">1.0</span></label>
      <input type="range" id="speed" min="0.1" max="5" step="0.1" value="1.0">
      // In JS: speedSlider.addEventListener('input', e => { state.speed = +e.target.value; document.getElementById('speed-val').textContent = state.speed.toFixed(1); renderer.render(scene, camera); });
  - These DOM text updates are HOW the automated interaction test detects that a control is alive. Without them, every Three.js control appears dead.
  - Never rely on the WebGL canvas pixel change alone — always pair every control with a DOM text readout.

OUTPUT — single JSON: {"path": "...", "content": "<full file>"}.
"""


CRITIQUE_SYSTEM = """You are a senior engineer doing a brutal pre-ship code review. You receive the plan, the source files, and the browser-verify result (which now includes mechanical interaction-test results — controls that produce no state change are flagged as "dead").

Pay SPECIAL attention to interaction-logic correctness — this is where recent projects have been failing:

- For each ui_feature in the plan: is the event listener wired? Does the handler actually mutate state? Does the visual update happen?
- Coordinate-math vs visual render: if the user clicks a node at (x, y), does the click handler use the SAME coordinate transform the render code uses? Off-by-one, transform-mismatch, and stale-DOM-reference bugs are the killer.
- Randomize / reset buttons: do they actually reset all the state they should, OR do they leave stale references that crash on next interaction?
- Drag-drop: is dragstart setting source ID? Does drop preventDefault before reading dataTransfer? Is the dropped element rendered or only added to a hidden array?
- Dialog boxes: are they being dismissed cleanly on next interaction, or do they pile up?
- Disappearing-element-on-click bugs: did the handler call removeChild on something it shouldn't?

Output JSON:
{
  "verdict": "ship" | "fix" | "redo",
  "must_fix": [{"file": "...", "issue": "...", "suggestion": "..."}],
  "should_improve": [...],
  "summary": "1-3 sentences"
}

Default to "fix" — only "ship" if genuinely flawless. "redo" only if architecture is broken.

DO NOT obsess over: WebGL warnings, autoplay policy hints, favicon 404s. Focus on real interaction bugs.
"""


FIX_SYSTEM = """Fix the listed issues. Output ONLY files that change, complete content (no diffs).

Rules:
- Address every issue.
- Don't break what works.
- Output JSON: {"files": [{"path": "...", "content": "..."}], "notes": "..."}
"""


POLISH_SYSTEM = """The project works correctly. Elevate it from "works" to "polished".

Add or improve where appropriate: visual identity, transitions, hover states, controls, instructions, accessibility, smarter defaults.

CRITICAL: do not break what already works. Only improve.

Return valid JSON: {"files": [{"path": "...", "content": "..."}], "notes": "..."}
Only include files that actually changed.
"""


QA_REVIEW_SYSTEM = """You are the QA Tester. Project Evolution gave you teeth: you are no longer a console-log validator. You are a USER-PATHWAY simulator + STATE-MANAGEMENT auditor.

You receive: the plan (especially `ui_features` with state_change + visual_response fields), the source files, and a mechanical interaction-test result from headless Chromium (clicked every button, changed every slider, recorded whether state changed).

Your job is to answer:

1. STATE-SYNC: For each interactive control in `ui_features`, when triggered, does the state mutate AND does the visual representation update accordingly? Specifically:
   - If a node is clicked, does the coordinate-math used by the click handler match the coordinate-math used by the renderer? (Off-by-one bugs, missed transform, stale ref → flag as critical.)
   - If a slider changes a parameter, does the visualization actually re-render with the new parameter?
   - If a button claims to "save" or "load" or "randomize", is something specific actually persisted/restored/changed? Or is it cosmetic?

2. POST-INTERACTION SURVIVAL: After clicking common buttons (Reset, Randomize, Save, etc.), do other elements still work? Do dialogs disappear cleanly? Do nodes persist or vanish unexpectedly? (The "disappearing element on randomize" bug pattern.)

3. PROMISED FEATURES vs REALITY: For every ui_feature in the plan, can a user actually use it via the deployed page? Or is it just listed?

4. DIALOG / ALERT NOISE: Are there alert() boxes or dialogs firing on every value change? That's a UX bug — flag as dead-pattern.

5. PIXEL / VISUAL: If interaction is supposed to draw on canvas, does the canvas show meaningful change? Not just any change — meaningful, visible-to-a-user change. (The "healthcare pixel issue" — canvas runs but produces no visually-coherent output.)

CRITERIA for verdict:

- non_functional: >50% of controls don't change state, OR a core promised feature is missing entirely, OR the page becomes non-interactive after first user action (disappear-on-click).
- partially_usable: 1-3 minor controls dead but core experience works.
- shippable: every promised feature actually does something visible/stateful.

OUTPUT — single JSON:
{
  "verdict": "shippable" | "partially_usable" | "non_functional",
  "summary": "1-2 sentences of judgement",
  "dead_controls": [{"control": "...", "expected": "...", "actual": "...", "fix": "..."}],
  "missing_features": [{"feature": "...", "why_missing": "...", "fix": "..."}],
  "state_sync_issues": [{"feature": "...", "problem": "coordinate mismatch / state-only / visual-only / disappearing element / etc", "fix": "..."}],
  "directives_for_future": ["0-3 imperative instructions for future projects"]
}

Be specific. "Buttons don't work" is useless. "The Randomize button (button.btn-randomize in app.js line 47) calls .splice() on the active node array but the renderer holds a stale reference to the old array — clicking Randomize causes nodes to disappear from view permanently" is right.
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
    text, meta = roles.call_with_fallback(
        client, role,
        system=system, user=user,
        max_tokens=max_tokens, temperature=temperature,
        json_mode=json_mode,
        validator=_parse_json,
    )
    return _parse_json(text), meta


def _type_failure_streaks(memory: dict) -> dict[str, int]:
    """Count how many consecutive recent failures each type has (unbroken by a success)."""
    failed = memory.get("failed_builds", [])
    projects = memory.get("projects", [])
    # Find the timestamp of the last successful ship
    last_ship_unix = max(
        (p.get("completed_at_unix", 0) for p in projects), default=0
    )
    # Count failures per type since last ship
    type_fails: dict[str, int] = {}
    for f in failed:
        if f.get("attempted_at_unix", 0) > last_ship_unix:
            pt = f.get("plan_type") or f.get("plan_pattern", "unknown")
            # Try to extract type from the plan name heuristic or from stored data
            # The failed_builds should store the type
            ft = f.get("project_type", "unknown")
            type_fails[ft] = type_fails.get(ft, 0) + 1
    return type_fails


def _banned_types(memory: dict) -> list[str]:
    """Types that have failed 3+ times consecutively since last ship. Auto-banned."""
    streaks = _type_failure_streaks(memory)
    return [t for t, count in streaks.items() if count >= 3 and t != "unknown"]


def _type_diversity_summary(memory: dict) -> str:
    """Analyze project type distribution and recommend next type."""
    projects = memory.get("projects", [])
    if not projects:
        return ""

    # Count by type
    type_counts: dict[str, int] = {}
    type_max_complexity: dict[str, int] = {}
    for p in projects:
        pt = p.get("project_type", "web_interactive")
        type_counts[pt] = type_counts.get(pt, 0) + 1
        c = p.get("complexity_score", 0)
        type_max_complexity[pt] = max(type_max_complexity.get(pt, 0), c)

    lines = ["\n── TYPE DIVERSITY REPORT ──"]
    lines.append("Types built so far:")
    for pt in PROJECT_TYPES:
        count = type_counts.get(pt, 0)
        max_c = type_max_complexity.get(pt, 0)
        ceiling = TYPE_COMPLEXITY_CEILING.get(pt, 50)
        status = "MAXED OUT" if max_c >= ceiling else f"room to grow (ceiling={ceiling})"
        lines.append(f"  {pt:20s}: {count:2d} shipped, max_complexity={max_c:3d}, {status}")

    # Never-tried types
    never_tried = [pt for pt in PROJECT_TYPES if type_counts.get(pt, 0) == 0]
    if never_tried:
        lines.append(f"\nNEVER TRIED (high priority): {', '.join(never_tried)}")

    # Maxed-out types
    maxed = [pt for pt in PROJECT_TYPES
             if type_max_complexity.get(pt, 0) >= TYPE_COMPLEXITY_CEILING.get(pt, 50)]
    if maxed:
        lines.append(f"MAXED OUT (avoid unless recovery): {', '.join(maxed)}")

    # Banned types (failed 3+ times consecutively since last ship)
    banned = _banned_types(memory)
    if banned:
        lines.append(f"\nBANNED (failed 3+ times in a row — DO NOT USE): {', '.join(banned)}")
        lines.append("These types are temporarily blocked. Pick a different type that the system can actually ship.")

    # Consecutive same-type streak
    recent_types = [p.get("project_type", "web_interactive") for p in projects[-3:]]
    if len(set(recent_types)) == 1 and len(recent_types) >= 2:
        lines.append(f"\nSTREAK WARNING: last {len(recent_types)} projects are all '{recent_types[0]}'. "
                     f"MUST switch to a different type now.")

    # Recommend next type (excluding banned)
    best_candidates = []
    for pt in TYPE_ESCALATION_ORDER:
        max_c = type_max_complexity.get(pt, 0)
        ceiling = TYPE_COMPLEXITY_CEILING.get(pt, 50)
        if max_c < ceiling and pt not in banned:
            best_candidates.append((type_counts.get(pt, 0), pt))
    if best_candidates:
        # Prefer least-used types that still have room
        best_candidates.sort()
        lines.append(f"\nRECOMMENDED NEXT TYPE (least used with room): {best_candidates[0][1]}")
        if len(best_candidates) > 1:
            lines.append(f"  Runner-up: {best_candidates[1][1]}")

    return "\n".join(lines)


def _summarize_history(memory: dict) -> str:
    recent = memory.get("projects", [])[-HISTORY_WINDOW:]
    if not recent:
        return "No previous projects. Start unpredictable; don't default to a web visualizer."
    lines = ["Recent project history:"]
    for p in recent:
        concepts = ", ".join((p.get("concepts_demonstrated") or [])[:5])
        lines.append(
            f"- {p.get('date')} \"{p.get('name')}\" "
            f"[type={p.get('project_type','web')}, c={p.get('complexity_score')}, "
            f"pattern={p.get('pattern','?')}, domain={p.get('domain','?')}] {concepts}"
        )
    cs = [p.get("complexity_score", 0) for p in recent]
    lines.append(f"\nRecent complexity max={max(cs)}. Floor for next: {max(cs)+1} (relaxed in recovery mode).")

    last5 = memory.get("projects", [])[-5:]
    rp = [p.get("pattern") for p in last5 if p.get("pattern")]
    rd = [p.get("domain") for p in last5 if p.get("domain")]
    rt = [p.get("project_type", "web_interactive") for p in last5]
    if rp:
        lines.append(f"Recent patterns (avoid): {', '.join(rp)}")
    if rd:
        lines.append(f"Recent domains (avoid): {', '.join(rd)}")
    if rt:
        lines.append(f"Recent project_types (favor different): {', '.join(rt)}")

    explored = memory.get("concepts_explored", [])
    if explored:
        lines.append(f"\nconcepts_explored (your novel_concepts must NOT all be in this list):\n{', '.join(explored[-50:])}")

    fb = (memory.get("failed_builds") or [])[-5:]
    if fb:
        lines.append(f"\nRecent REFUSED builds (architect tried, QA refused):")
        for f in fb:
            lines.append(
                f"- \"{f.get('plan_name','?')}\" c={f.get('plan_complexity','?')} "
                f"pattern={f.get('plan_pattern','?')} -> {f.get('refusal_stage','?')}: "
                f"dead={len(f.get('qa_dead_controls') or [])} "
                f"missing={len(f.get('qa_missing_features') or [])}"
            )
        lines.append("Do NOT repeat the patterns/domains/types of refused builds — they failed.")
    return "\n".join(lines)


def _validate_plan(plan: dict, memory: dict) -> None:
    required = {
        "name", "description", "long_description", "language", "tech_stack",
        "complexity_score", "concepts_demonstrated", "novel_concepts",
        "advancement_axis", "is_web_project", "safety_notes",
        "architecture", "files", "ui_features", "verification_criteria",
        "pattern", "domain", "visual_identity", "project_type",
    }
    missing = required - plan.keys()
    if missing:
        raise PipelineError(f"Plan missing required fields: {sorted(missing)}")
    if not NAME_RE.match(plan["name"]):
        raise PipelineError(f"Invalid plan name: {plan['name']!r}")

    pt = plan.get("project_type")
    if pt not in PROJECT_TYPES:
        raise PipelineError(f"project_type must be one of {PROJECT_TYPES}; got {pt!r}")

    # is_web_project must agree with project_type
    web_types = {"web_interactive", "web_3d", "game_web", "generative_art"}
    expected_web = pt in web_types
    if bool(plan.get("is_web_project")) != expected_web:
        plan["is_web_project"] = expected_web

    complexity = int(plan["complexity_score"])

    files = plan.get("files") or []
    # Scope minimums scale with complexity
    if complexity >= 13:
        min_files = 6
    elif complexity >= 10:
        min_files = 5
    else:
        min_files = 3
    if len(files) < min_files:
        raise PipelineError(
            f"Plan with complexity {complexity} needs >={min_files} files. Got {len(files)}."
        )

    # Recovery mode: if failures dominate since last ship, relax floor + rotation.
    last_success_unix = max(
        (p.get("completed_at_unix", 0) for p in (memory.get("projects") or [])),
        default=0,
    )
    fails_since_last_ship = sum(
        1 for f in (memory.get("failed_builds") or [])
        if f.get("attempted_at_unix", 0) > last_success_unix
    )
    in_recovery = fails_since_last_ship >= 3

    # Hard advancement gate
    recent = memory.get("projects", [])[-7:]
    if recent and not in_recovery:
        max_recent = max(p.get("complexity_score", 0) for p in recent)
        floor = max_recent + 1
        if complexity < floor:
            raise PipelineError(
                f"complexity_score={complexity} below floor {floor} (max recent={max_recent}). "
                "The scale is open-ended; surpass yesterday."
            )

    # Novel concepts gate
    explored = set(memory.get("concepts_explored", []))
    novel = plan.get("novel_concepts") or []
    truly_novel = [c for c in novel if c not in explored]
    novel_min = 1 if in_recovery else 2
    if len(truly_novel) < novel_min:
        raise PipelineError(
            f"novel_concepts must include >={novel_min} entries NOT in concepts_explored. "
            f"truly novel={truly_novel}"
        )

    # File path safety + no compiled languages
    forbidden_exts = {".ts", ".tsx", ".jsx", ".scss", ".less", ".vue",
                      ".svelte", ".coffee", ".pug", ".sass"}
    has_index = False
    has_readme = False
    for fs in files:
        path = fs.get("path", "")
        p = Path(path)
        if not path or p.is_absolute() or ".." in p.parts:
            raise PipelineError(f"Unsafe file path: {path!r}")
        if p.suffix.lower() in forbidden_exts:
            raise PipelineError(
                f"File {path!r} requires a build step. Plain .js/.html/.css/.py/.md only."
            )
        if p.name.lower() == "index.html":
            has_index = True
        if p.name.lower() == "readme.md":
            has_readme = True

    # ALL projects need index.html for GitHub Pages visual showcase
    if not has_index:
        raise PipelineError(
            f"project_type={pt} requires index.html at repo root. "
            "Every project must have a visual showcase page for the dashboard."
        )
    if pt == "python_tool":
        py_files = [f for f in files if f.get("path", "").endswith(".py")]
        if not py_files:
            raise PipelineError(
                "project_type=python_tool requires at least one .py file."
            )

    # Type ban enforcement — types that failed 3+ times are banned regardless of recovery
    banned = _banned_types(memory)
    if pt in banned:
        raise PipelineError(
            f"project_type={pt!r} is BANNED (failed {_type_failure_streaks(memory).get(pt, 0)} "
            f"consecutive times since last ship). Pick a different type. "
            f"Available: {[t for t in PROJECT_TYPES if t not in banned]}"
        )

    # Type diversity enforcement
    all_projects = memory.get("projects", [])
    if all_projects and not in_recovery:
        last_type = all_projects[-1].get("project_type", "web_interactive")
        # Can't repeat the same type twice in a row
        if pt == last_type:
            raise PipelineError(
                f"project_type={pt!r} was used in the previous build. "
                f"Must switch types for diversity. Try one of: "
                f"{[t for t in PROJECT_TYPES if t != pt]}"
            )
        # Can't use a type that has reached its complexity ceiling
        type_max_c = max(
            (p.get("complexity_score", 0) for p in all_projects
             if p.get("project_type") == pt),
            default=0,
        )
        ceiling = TYPE_COMPLEXITY_CEILING.get(pt, 50)
        if type_max_c >= ceiling:
            raise PipelineError(
                f"project_type={pt!r} has reached its complexity ceiling "
                f"(max shipped={type_max_c}, ceiling={ceiling}). "
                f"Escalate to a higher-ceiling type."
            )

    # Pattern + domain rotation (relaxed in recovery)
    last5 = memory.get("projects", [])[-5:]
    recent_patterns = [p.get("pattern") for p in last5 if p.get("pattern")]
    recent_domains = [p.get("domain") for p in last5 if p.get("domain")]
    pattern = (plan.get("pattern") or "").strip().lower()
    domain = (plan.get("domain") or "").strip()
    if not pattern:
        raise PipelineError("`pattern` field required")
    if not domain:
        raise PipelineError("`domain` field required")
    if not in_recovery:
        if pattern in [p.lower() for p in recent_patterns if p]:
            raise PipelineError(
                f"pattern={pattern!r} was used in last 5 ({recent_patterns})."
            )
        if domain in recent_domains:
            raise PipelineError(
                f"domain={domain!r} was used in last 5 ({recent_domains})."
            )


def _ensure_readme_planned(plan: dict) -> None:
    if not any(Path(f["path"]).name.lower() == "readme.md" for f in plan["files"]):
        plan["files"].append({
            "path": "README.md",
            "role": "Project overview, how to run, controls, what it demonstrates.",
            "key_functions": [],
        })


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


# ─────────────────────── Stages ─────────────────────────────────────────

def stage_plan(client: OpenAI, memory: dict,
               ceo_directives: list[str] | None = None,
               cso_directives: list[str] | None = None) -> dict:
    """Architect Conference: 2 candidates from gpt-4o-mini, Judge from gpt-4o."""
    history = _summarize_history(memory)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    diversity = _type_diversity_summary(memory)
    base_user = f"Today is {today}. Produce today's design plan.\n\n{history}{diversity}"
    if ceo_directives:
        base_user += "\n\nCEO DIRECTIVES (visionary, you must obey):\n" + "\n".join(f"- {d}" for d in ceo_directives)
    if cso_directives:
        base_user += "\n\nCSO DIRECTIVES (Chief Science Officer, algorithmic depth):\n" + "\n".join(f"- {d}" for d in cso_directives)

    candidate_roles = ["architect_candidate_a", "architect_candidate_b"]
    candidates: list[dict] = []
    last_err: str | None = None

    for round_num in range(1, 3):
        log.info("ARCHITECT CONFERENCE round %d", round_num)
        for role in candidate_roles:
            try:
                user = base_user
                if last_err:
                    user += f"\n\nPRIOR plan rejected with: {last_err}\nFix it."
                plan, meta = _call_role(client, role, PLAN_SYSTEM, user,
                                        max_tokens=4000, temperature=1.0)  # high temp for unpredictability
                _validate_plan(plan, memory)
                _ensure_readme_planned(plan)
                plan["__model__"] = meta["model"]
                plan["__role__"] = role
                candidates.append(plan)
                log.info("✓ Candidate from %s: %s [type=%s] c=%d",
                         meta["model"], plan["name"],
                         plan.get("project_type", "?"), plan["complexity_score"])
            except PipelineError as e:
                last_err = str(e)
                log.warning("✗ Candidate %s rejected: %s", role, last_err)
            except roles.AllModelsFailed as e:
                log.warning("✗ Candidate %s exhausted models: %s", role, e)
        if candidates:
            break

    if not candidates:
        raise PipelineError(
            f"Architect conference produced 0 valid candidates. Last error: {last_err}"
        )

    if len(candidates) == 1:
        log.info("Only one valid candidate; skipping Judge.")
        return candidates[0]

    # Judge with predictability filter
    judge_input = json.dumps(
        [{k: v for k, v in c.items() if not k.startswith("__")} for c in candidates],
        indent=2,
    )[:18000]
    judge_user = (
        f"Today is {today}.\n\n{history}\n\n"
        f"You received {len(candidates)} candidate plans. Apply the predictability test. "
        "If all candidates are too predictable (web visualizer, dashboard, explorer with "
        "sliders + canvas), REJECT them and propose your OWN unpredictable plan in the "
        "same JSON schema. Otherwise, pick the strongest unpredictable candidate or "
        "synthesize a stronger one. Output ONE plan in standard schema.\n\n"
        f"CANDIDATES:\n{judge_input}"
    )
    final, meta = _call_role(client, "architect_judge",
                             JUDGE_SYSTEM, judge_user, max_tokens=4000)
    _validate_plan(final, memory)
    _ensure_readme_planned(final)
    final["__model__"] = meta["model"]
    final["__role__"] = "architect_judge"
    final["__candidates_considered__"] = len(candidates)
    final["__candidate_models__"] = [c["__model__"] for c in candidates]
    log.info("Judge picked plan: %s [type=%s] c=%d (from %d candidates)",
             final["name"], final.get("project_type", "?"),
             final["complexity_score"], len(candidates))
    return final


def stage_implement(client: OpenAI, plan: dict,
                    file_spec: dict, prior: dict[str, str]) -> tuple[str, str, dict]:
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
        raise PipelineError(f"File content too short for {file_spec['path']!r}")
    return file_spec["path"], out["content"], meta


def stage_critique(client: OpenAI, plan: dict,
                   files: dict[str, str], browser_result: dict | None) -> dict:
    plan_brief = {k: plan[k] for k in
                  ("name", "description", "verification_criteria", "ui_features",
                   "concepts_demonstrated", "complexity_score", "project_type")
                  if k in plan}
    files_concat = _concat_files(files, budget=22000)
    browser_summary = json.dumps(browser_result or {}, indent=2)[:3500]
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"FILES:\n{files_concat}\n\n"
        f"BROWSER VERIFY:\n{browser_summary}"
    )

    reports: list[dict] = []
    for role in ("reviewer_a", "reviewer_b"):
        try:
            report, meta = _call_role(client, role, CRITIQUE_SYSTEM, user, max_tokens=2500)
            report["__model__"] = meta["model"]
            reports.append(report)
            log.info("Reviewer %s: verdict=%s, must_fix=%d",
                     role, report.get("verdict"), len(report.get("must_fix") or []))
        except (PipelineError, roles.AllModelsFailed) as e:
            log.warning("Reviewer %s failed: %s", role, e)

    if not reports:
        raise PipelineError("Critique conference: every reviewer failed.")

    merged_must_fix: list[dict] = []
    seen: set[str] = set()
    for r in reports:
        for item in (r.get("must_fix") or []):
            if not isinstance(item, dict):
                continue
            key = (item.get("issue", "")[:60]).lower().strip()
            if key and key not in seen:
                seen.add(key)
                merged_must_fix.append({**item, "raised_by": r.get("__model__", "?")})

    verdicts = [r.get("verdict", "fix") for r in reports]
    verdict = "redo" if "redo" in verdicts else ("fix" if "fix" in verdicts else "ship")
    summary = " || ".join(f"[{r.get('__model__','?')}] {r.get('summary','')[:200]}" for r in reports)

    return {
        "verdict": verdict,
        "must_fix": merged_must_fix,
        "should_improve": [s for r in reports for s in (r.get("should_improve") or [])],
        "summary": summary[:800],
        "_reviews": [{"model": r.get("__model__"), "verdict": r.get("verdict"),
                      "n_must_fix": len(r.get("must_fix") or [])} for r in reports],
    }


def stage_fix(client: OpenAI, plan: dict,
              files: dict[str, str], issues: list[str]) -> dict[str, str]:
    plan_brief = {k: plan[k] for k in
                  ("name", "verification_criteria", "ui_features", "project_type")
                  if k in plan}
    files_concat = _concat_files(files, budget=14000)
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"CURRENT FILES:\n{files_concat}\n\n"
        f"ISSUES TO FIX:\n" + "\n".join(f"- {i}" for i in issues)
        + "\n\nOutput ONLY files that change. Keep response under 6000 tokens."
    )
    out, meta = _call_role(client, "fixer", FIX_SYSTEM, user, max_tokens=6000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("Fixer (%s) produced %d update(s)", meta["model"], len(updates))
    return updates


def stage_polish(client: OpenAI, plan: dict,
                 files: dict[str, str]) -> dict[str, str]:
    plan_brief = {k: plan[k] for k in
                  ("name", "description", "ui_features", "project_type") if k in plan}
    files_concat = _concat_files(files, budget=14000)
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"WORKING FILES:\n{files_concat}\n\n"
        "Only include files you actually polished. Keep response under 6000 tokens."
    )
    out, meta = _call_role(client, "polisher", POLISH_SYSTEM, user, max_tokens=6000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("Polisher (%s) produced %d update(s)", meta["model"], len(updates))
    return updates


def stage_qa_review(client: OpenAI, plan: dict,
                    files: dict[str, str],
                    browser_result: dict | None) -> dict:
    plan_brief = {k: plan[k] for k in
                  ("name", "description", "ui_features", "verification_criteria",
                   "concepts_demonstrated", "project_type") if k in plan}
    files_concat = _concat_files(files, budget=14000)
    metrics = (browser_result or {}).get("metrics") or {}
    interaction = metrics.get("interaction") or {}
    interaction_summary = json.dumps(interaction, indent=2)[:2500]
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"INTERACTION TEST (headless Chromium drove each control):\n{interaction_summary}\n\n"
        f"FINAL FILES:\n{files_concat}\n\n"
        "Evaluate state-management sync, coordinate-math correctness, post-interaction survival, "
        "and visual-render integrity. Return single JSON per the schema."
    )
    out, meta = _call_role(client, "qa_tester", QA_REVIEW_SYSTEM, user, max_tokens=2500)
    out["__model__"] = meta["model"]
    log.info("QA review (%s): verdict=%s dead=%d missing=%d state_sync_issues=%d",
             meta["model"], out.get("verdict"),
             len(out.get("dead_controls") or []),
             len(out.get("missing_features") or []),
             len(out.get("state_sync_issues") or []))
    return out


def stage_qa_fix(client: OpenAI, plan: dict,
                 files: dict[str, str], issues: list[str]) -> dict[str, str]:
    plan_brief = {k: plan[k] for k in
                  ("name", "ui_features", "verification_criteria", "project_type")
                  if k in plan}
    files_concat = _concat_files(files, budget=14000)
    user = (
        f"PLAN:\n{json.dumps(plan_brief, indent=2)}\n\n"
        f"CURRENT FILES:\n{files_concat}\n\n"
        f"USABILITY + STATE-SYNC ISSUES TO FIX:\n"
        + "\n".join(f"- {i}" for i in issues)
        + "\n\nGuidance:\n"
          "- For coordinate-math bugs: ensure click-handler and renderer use the SAME "
          "transform / scale / origin. Pull it into a shared function.\n"
          "- For state-only bugs (button mutates state but visual doesn't update): the "
          "handler must call the renderer after mutation, OR the state must be observable.\n"
          "- For disappearing-element bugs: don't splice the array the renderer iterates; "
          "rebuild the array OR use immutable updates.\n"
          "- For dialog-on-every-change bugs: replace alert() with inline non-blocking "
          "feedback (text label, badge, etc.).\n"
          "- For pixel/canvas issues: confirm canvas.width/height are set BEFORE drawing; "
          "check fillStyle/strokeStyle aren't transparent or same-as-background.\n"
          "Output FULL updated files. Same FIX schema."
    )
    out, meta = _call_role(client, "qa_fixer", FIX_SYSTEM, user, max_tokens=6000)
    updates = {f["path"]: f["content"] for f in (out.get("files") or [])
               if isinstance(f, dict) and "path" in f and "content" in f}
    log.info("QA fixer (%s) produced %d update(s)", meta["model"], len(updates))
    return updates
