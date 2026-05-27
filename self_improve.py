"""
self_improve.py — The system patches its own pipeline source code.

After each CEO review, this agent:
  1. Reads memory_log.json to find recurring failure patterns
  2. Reads its own source files (pipeline.py, verifier.py, executive.py)
  3. Asks a CTO-level LLM to propose ONE surgical code patch
  4. Validates the patch (Python syntax check)
  5. Applies it, commits, and logs the improvement to memory_log.json

This is the self-healing layer above the CEO. The CEO changes strategy.
The CTO changes the code itself.

Zero human intervention required.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

import roles

log = logging.getLogger("brain.self_improve")

MEMORY_PATH = Path("memory_log.json")
SELF_IMPROVE_KEY = "self_improvements"

# Files the CTO is allowed to patch
PATCHABLE_FILES = {
    "pipeline.py": Path("pipeline.py"),
    "verifier.py": Path("verifier.py"),
    "executive.py": Path("executive.py"),
    "dashboard.py": Path("dashboard.py"),
}

# Named sections to extract from source files — keyed by failure pattern.
# We only send the relevant section to stay within the 8000-token API limit.
_SECTION_MARKERS = {
    "pipeline.py": {
        "IMPLEMENT_SYSTEM": ("IMPLEMENT_SYSTEM", "CRITIQUE_SYSTEM"),
        "PLAN_SYSTEM":      ("PLAN_SYSTEM", "JUDGE_SYSTEM"),
        "CRITIQUE_SYSTEM":  ("CRITIQUE_SYSTEM", "FIX_SYSTEM"),
        "QA_REVIEW_SYSTEM": ("QA_REVIEW_SYSTEM", 'if __name__'),
        "_validate_plan":   ("def _validate_plan", "def stage_plan"),
    },
    "verifier.py": {
        "_SNAPSHOT_JS":     ("_SNAPSHOT_JS", "_LIST_CONTROLS_JS"),
        "_TRIGGER_JS":      ("_TRIGGER_JS", "def _run_interaction_test"),
        "interaction_test": ("def _run_interaction_test", "def verify_web"),
        "issue_detection":  ("# Heuristic issue detection", "return {"),
    },
    "executive.py": {
        "CEO_SYSTEM":       ("CEO_SYSTEM", "CSO_SYSTEM"),
    },
}


def _extract_section(file_path: Path, start_marker: str, end_marker: str) -> str:
    """Extract the text between two string markers in a file."""
    content = file_path.read_text(encoding="utf-8")
    s = content.find(start_marker)
    if s < 0:
        return content[:3000]  # fallback
    e = content.find(end_marker, s + len(start_marker))
    if e < 0:
        return content[s:s + 3000]
    return content[s:e]


def _pick_relevant_source(analysis: dict) -> str:
    """
    Pick only the source sections most relevant to the top failure pattern.
    Keeps total chars well under the 8000-token API limit.
    """
    top_reason = max(
        analysis.get("by_reason", {}).items(),
        key=lambda x: x[1],
        default=("dead_controls", 1)
    )[0]
    top_type = max(
        analysis.get("by_type", {}).items(),
        key=lambda x: x[1],
        default=("web_3d", 1)
    )[0]

    sections = []

    if top_reason == "dead_controls":
        # The engineer prompt is the fix target
        sections.append(("pipeline.py", "IMPLEMENT_SYSTEM", "CRITIQUE_SYSTEM"))
        if top_type == "web_3d":
            sections.append(("verifier.py", "_SNAPSHOT_JS", "_LIST_CONTROLS_JS"))
            sections.append(("verifier.py", "_TRIGGER_JS", "def _run_interaction_test"))
    elif top_reason == "blank_canvas":
        sections.append(("verifier.py", "# Heuristic issue detection", "return {"))
        sections.append(("pipeline.py", "IMPLEMENT_SYSTEM", "CRITIQUE_SYSTEM"))
    elif top_reason in ("concept_exhaustion", "type_ban"):
        sections.append(("pipeline.py", "PLAN_SYSTEM", "JUDGE_SYSTEM"))
        sections.append(("executive.py", "CEO_SYSTEM", "CSO_SYSTEM"))
    else:
        sections.append(("pipeline.py", "IMPLEMENT_SYSTEM", "CRITIQUE_SYSTEM"))

    parts = []
    total = 0
    MAX_TOTAL = 5000  # chars, safely under 8k tokens

    for fname, start, end in sections:
        fpath = PATCHABLE_FILES.get(fname)
        if not fpath or not fpath.exists():
            continue
        snippet = _extract_section(fpath, start, end)
        if total + len(snippet) > MAX_TOTAL:
            snippet = snippet[:MAX_TOTAL - total]
        parts.append(f"=== {fname} | section: {start[:40]} ===\n{snippet}")
        total += len(snippet)
        if total >= MAX_TOTAL:
            break

    return "\n\n".join(parts)

# How many recent failures to analyse
FAILURE_WINDOW = 30
# Don't patch if fewer than this many failures exist since last improvement
MIN_FAILURES_TO_TRIGGER = 5


# ─────────────────────── Failure Pattern Analysis ───────────────────────────

def _analyse_failures(memory: dict) -> dict[str, Any]:
    """
    Extract structured failure patterns from memory_log.json.
    Returns a summary the CTO LLM can reason about.
    """
    failed = (memory.get("failed_builds") or [])[-FAILURE_WINDOW:]
    if not failed:
        return {"total": 0, "by_type": {}, "by_reason": {}, "streaks": {}, "raw": []}

    by_type: Counter = Counter()
    by_reason: Counter = Counter()
    dead_control_patterns: Counter = Counter()
    error_snippets: list[str] = []

    for f in failed:
        pt = f.get("project_type", "unknown")
        by_type[pt] += 1

        reason = f.get("refusal_reason", "")
        # Normalise reason to a short key
        if "dead control" in reason.lower() or "dead_control" in reason.lower():
            by_reason["dead_controls"] += 1
        elif "blank" in reason.lower() and "canvas" in reason.lower():
            by_reason["blank_canvas"] += 1
        elif "non_functional" in reason.lower():
            by_reason["non_functional"] += 1
        elif "novel concept" in reason.lower() or "concepts_explored" in reason.lower():
            by_reason["concept_exhaustion"] += 1
        elif "complexity" in reason.lower():
            by_reason["complexity_floor"] += 1
        elif "missing" in reason.lower() and "feature" in reason.lower():
            by_reason["missing_features"] += 1
        else:
            by_reason["other"] += 1

        for dc in f.get("qa_dead_controls") or []:
            ctrl = dc.get("control", "")
            expected = dc.get("expected", "")
            key = f"{ctrl[:60]} | {expected[:60]}"
            dead_control_patterns[key] += 1

    # Failure streak per type (consecutive from most recent)
    streaks: dict[str, int] = {}
    if failed:
        streak_type = failed[-1].get("project_type", "unknown")
        count = 0
        for f in reversed(failed):
            if f.get("project_type") == streak_type:
                count += 1
            else:
                break
        streaks[streak_type] = count

    # Most common dead control patterns
    top_dead = dead_control_patterns.most_common(5)

    # Recent error snippets
    for f in failed[-10:]:
        r = f.get("refusal_reason", "")
        if r and r not in error_snippets:
            error_snippets.append(r[:200])

    return {
        "total_failures": len(failed),
        "by_type": dict(by_type.most_common()),
        "by_reason": dict(by_reason.most_common()),
        "top_dead_controls": [{"pattern": p, "count": c} for p, c in top_dead],
        "current_streak": streaks,
        "recent_errors": error_snippets,
    }


def _failures_since_last_improvement(memory: dict) -> int:
    improvements = memory.get(SELF_IMPROVE_KEY) or []
    if not improvements:
        return len(memory.get("failed_builds") or [])
    last_ts = improvements[-1].get("applied_at_unix", 0)
    return sum(
        1 for f in (memory.get("failed_builds") or [])
        if f.get("attempted_at_unix", 0) > last_ts
    )


def _previous_improvements(memory: dict) -> str:
    improvements = memory.get(SELF_IMPROVE_KEY) or []
    if not improvements:
        return "(none yet)"
    lines = []
    for imp in improvements[-10:]:
        lines.append(
            f"- {imp.get('applied_at','?')} | file={imp.get('file','?')} | "
            f"rationale={imp.get('rationale','?')[:120]}"
        )
    return "\n".join(lines)


# ─────────────────────── CTO System Prompt ──────────────────────────────────

CTO_SYSTEM = """You are the CTO of an autonomous AI software-creation pipeline. You have full read access to the pipeline's own source code and write access to apply patches. Your job is to make the pipeline fix its own recurring problems — no human will do this for you.

You receive:
1. FAILURE ANALYSIS — structured breakdown of recent build failures (what types fail, why, which controls die)
2. SOURCE FILES — the current content of pipeline.py, verifier.py, and executive.py
3. PREVIOUS SELF-IMPROVEMENTS — patches you have already applied (do NOT re-apply the same fix)

Your output is ONE surgical code patch. Rules:

WHAT YOU CAN FIX:
- Prompts in pipeline.py (PLAN_SYSTEM, IMPLEMENT_SYSTEM, CRITIQUE_SYSTEM, QA_REVIEW_SYSTEM) — add guidance the engineer is missing
- Validation logic in pipeline.py (_validate_plan, TYPE_COMPLEXITY_CEILING, etc.)
- Verifier heuristics in verifier.py (_SNAPSHOT_JS, _TRIGGER_JS, issue detection thresholds)
- CEO/CSO prompts in executive.py (add new self-healing rules, adjust review window)
- Type ban thresholds, complexity ceilings, recovery mode triggers

WHAT YOU MUST NOT TOUCH:
- GitHub API calls, repo creation, Pages enablement (brain.py publish logic)
- Workflow YAML files
- memory_log.json (that is managed by the pipeline, not you)
- dashboard.py rendering logic
- Any credentials, tokens, or secrets

PATCH FORMAT — output ONLY this JSON, no prose, no markdown fences:
{
  "file": "pipeline.py",
  "old_string": "exact verbatim substring to replace (must be unique in the file)",
  "new_string": "the replacement — must be valid Python",
  "rationale": "1-2 sentences: what failure pattern this fixes and how",
  "failure_pattern_targeted": "dead_controls | blank_canvas | non_functional | concept_exhaustion | type_ban | other",
  "confidence": "high | medium | low"
}

DECISION RULES:
- If the same dead_control pattern appears 3+ times: fix the IMPLEMENT_SYSTEM prompt to give the engineer the specific wiring pattern
- If a type keeps failing with blank canvas: fix the verifier to skip that check for that type
- If concept exhaustion is rising: expand the domain list in PLAN_SYSTEM
- If the CEO keeps recommending banned types: tighten the CEO self-healing rule
- If nothing is clearly the top issue: improve the engineer prompt for the most-failed project_type

Output ONLY the JSON patch. If you cannot identify a safe, high-confidence fix, output:
{"file": null, "rationale": "No safe patch identified: <reason>", "confidence": "low"}
"""


# ─────────────────────── Apply Patch ────────────────────────────────────────

def _apply_patch(patch: dict) -> tuple[bool, str]:
    """
    Apply the CTO's patch to the target file.
    Returns (success, message).
    """
    fname = patch.get("file")
    if not fname:
        return False, "No file specified in patch."

    target = PATCHABLE_FILES.get(fname)
    if not target:
        return False, f"File {fname!r} is not in PATCHABLE_FILES — refusing."

    if not target.exists():
        return False, f"File {target} does not exist."

    old = patch.get("old_string", "")
    new = patch.get("new_string", "")

    if not old or not new:
        return False, "Patch missing old_string or new_string."

    content = target.read_text(encoding="utf-8")

    # Safety: old_string must appear EXACTLY ONCE
    count = content.count(old)
    if count == 0:
        return False, f"old_string not found in {fname}. May have already been patched."
    if count > 1:
        return False, f"old_string appears {count} times in {fname} — too ambiguous to patch safely."

    patched = content.replace(old, new, 1)

    # Syntax check for Python files
    if fname.endswith(".py"):
        try:
            ast.parse(patched)
        except SyntaxError as e:
            return False, f"Syntax error in patched {fname}: {e}"

    target.write_text(patched, encoding="utf-8")
    return True, f"Patched {fname}: replaced {len(old)} chars with {len(new)} chars."


# ─────────────────────── Git Commit ─────────────────────────────────────────

def _git_commit(fname: str, rationale: str) -> bool:
    try:
        subprocess.run(["git", "add", fname], check=True, capture_output=True)
        msg = f"self-improve: patch {fname} — {rationale[:100]}"
        subprocess.run(["git", "commit", "-m", msg], check=True, capture_output=True)
        subprocess.run(["git", "push"], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        log.error("Git commit failed: %s", e.stderr.decode() if e.stderr else str(e))
        return False


# ─────────────────────── Main ────────────────────────────────────────────────

def run_self_improve(memory_log_path: Path = MEMORY_PATH) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        log.error("GITHUB_TOKEN env var is required.")
        return 2

    # Load memory
    if not memory_log_path.exists():
        log.info("No memory log yet — skipping self-improvement.")
        return 0

    memory = json.loads(memory_log_path.read_text(encoding="utf-8"))

    # Check if there's enough new failure data since last improvement
    failures_since = _failures_since_last_improvement(memory)
    log.info("Failures since last self-improvement: %d", failures_since)
    if failures_since < MIN_FAILURES_TO_TRIGGER:
        log.info("Not enough new failures (%d < %d) — skipping.", failures_since, MIN_FAILURES_TO_TRIGGER)
        return 0

    # Analyse failure patterns
    analysis = _analyse_failures(memory)
    log.info("Failure analysis: %s", {k: v for k, v in analysis.items() if k != "raw"})

    if analysis["total_failures"] == 0:
        log.info("No failures to analyse.")
        return 0

    # Extract only the relevant source sections (stays within 8k token API limit)
    sources = _pick_relevant_source(analysis)
    prev = _previous_improvements(memory)

    user_prompt = (
        f"FAILURE ANALYSIS (last {FAILURE_WINDOW} builds):\n"
        f"{json.dumps(analysis, indent=2)}\n\n"
        f"PREVIOUS SELF-IMPROVEMENTS ALREADY APPLIED:\n{prev}\n\n"
        f"SOURCE FILES:\n{sources}\n\n"
        f"Identify the most impactful single patch. Output only the JSON patch."
    )

    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )

    try:
        text, meta = roles.call_with_fallback(
            client, "cto",
            system=CTO_SYSTEM,
            user=user_prompt,
            max_tokens=3000,
            temperature=0.3,  # Low temp — precise surgical patches
        )
    except roles.AllModelsFailed as e:
        log.error("CTO LLM call failed: %s", e)
        return 1

    # Parse patch JSON
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    s, e_idx = text.find("{"), text.rfind("}")
    if s < 0 or e_idx < 0:
        log.error("CTO output is not valid JSON: %s", text[:300])
        return 1

    try:
        patch = json.loads(text[s:e_idx + 1])
    except json.JSONDecodeError as e:
        log.error("CTO JSON parse error: %s\n%s", e, text[:300])
        return 1

    log.info("CTO patch proposal: file=%s confidence=%s rationale=%s",
             patch.get("file"), patch.get("confidence"), patch.get("rationale", "")[:120])

    # Skip low-confidence or null patches
    if not patch.get("file"):
        log.info("CTO declined to patch: %s", patch.get("rationale", "no reason given"))
        return 0

    if patch.get("confidence") == "low":
        log.info("CTO confidence is low — skipping patch to avoid breaking the pipeline.")
        return 0

    # Apply
    ok, msg = _apply_patch(patch)
    log.info("Patch result: %s — %s", "OK" if ok else "FAILED", msg)

    if not ok:
        log.warning("Patch not applied: %s", msg)
        return 0  # Non-fatal — just log and continue

    # Commit
    committed = _git_commit(patch["file"], patch.get("rationale", "self-improvement"))
    if committed:
        log.info("Self-improvement committed to repo.")
    else:
        log.warning("Patch applied locally but git commit failed.")

    # Record the improvement in memory
    record = {
        "applied_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "applied_at_unix": int(datetime.now(timezone.utc).timestamp()),
        "file": patch.get("file"),
        "rationale": patch.get("rationale", ""),
        "failure_pattern_targeted": patch.get("failure_pattern_targeted", "unknown"),
        "confidence": patch.get("confidence", "?"),
        "model": meta.get("model", "?"),
        "failures_analysed": analysis["total_failures"],
        "committed": committed,
    }
    memory.setdefault(SELF_IMPROVE_KEY, []).append(record)
    memory_log_path.write_text(
        json.dumps(memory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Commit memory update too
    try:
        subprocess.run(["git", "add", str(memory_log_path)], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "self-improve: log improvement record"],
                       check=True, capture_output=True)
        subprocess.run(["git", "push"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pass  # Memory log commit is best-effort

    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    sys.exit(run_self_improve())
