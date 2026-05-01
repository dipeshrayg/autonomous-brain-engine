"""
executive.py - The CEO role.

The CEO is a meta-watchdog. It runs on its own schedule (every 6 hours via
.github/workflows/ceo_review.yml) and asks: "Is the pipeline producing real
work that's actually advancing, or is it shipping mediocre projects that
just barely satisfy the validators?"

Concretely, the CEO:
    1. Reads memory_log.json and looks at the last 8 projects in detail.
    2. Computes mechanical metrics — complexity trajectory, file/LOC trend,
       quality-cycle counts, novel-concept density, pattern/domain spread.
    3. Asks an LLM (gpt-4o by default) to evaluate the trajectory against
       a strict rubric: design level, complexity progression, UX richness,
       diversity of language/tech, and presence/absence of staleness.
    4. Issues a small set of directives that the next plan stage must obey.
    5. Appends the verdict + directives to memory_log.ceo_reviews[] and
       commits it back.

The next plan stage reads the most-recent CEO review (if recent — within
36 hours) and prepends its directives to the architect conference prompt.
This is the closed loop that prevents the pipeline from drifting.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

import roles

log = logging.getLogger("brain.executive")

CEO_REVIEW_WINDOW = 8        # how many recent projects the CEO examines
CEO_DIRECTIVE_TTL_HOURS = 36  # plan stages older than this ignore the directives


CEO_SYSTEM = """You are the CEO of an autonomous AI software-creation pipeline. The system designs, codes, tests, and ships browser-runnable software projects multiple times a day. Your job is META: you don't write code, you evaluate whether the system as a whole is producing genuinely advancing, high-quality, diverse work — or whether it's drifting toward mediocre projects that just barely pass the validators.

Be ruthlessly strict. The pipeline already has automated gates for complexity score, novel concepts, pattern/domain rotation. Those gates pass mechanically. Your job is to look BEYOND the mechanical pass — to ask the questions the gates can't answer:

- Are the projects genuinely more sophisticated, or are they just adding superficial complexity to satisfy the validator?
- Is the user experience actually rich — multi-pane layouts, keyboard shortcuts, persistence, real-time feedback — or is it three buttons and a slider every time?
- Are the visualizations actually informative, or are they decorative?
- Is the language/tech diversity real, or is it always plain JS + Canvas with a different label?
- Is the system exploring genuinely novel domains, or is it cycling through visualizers/simulators dressed up differently?
- Are recent projects polished to a level a senior engineer would ship, or do they look like exam-question solutions?

Your output is a JSON document. The next plan stage will read your `directives` and obey them. Use this leverage. Be specific.

OUTPUT — single JSON object, no prose, no markdown fences:
{
  "verdict": "thriving" | "acceptable" | "drifting" | "alarming",
  "concerns": [
    "1-3 sentence specific concerns about recent work — name projects by name where relevant"
  ],
  "directives": [
    "imperative instructions for the NEXT project. each one a single concrete thing the architect MUST do"
  ],
  "praise": [
    "what the pipeline did well in this window (use sparingly — this is the part that gets least improvement)"
  ],
  "summary": "one paragraph executive summary"
}

Rules for directives:
- Each is imperative, concrete, achievable in a single project.
- 3-6 directives total. More is dilution.
- Push the system to do something it has NOT done well recently.
- Examples: 'Use a multi-pane workspace layout (left rail + main canvas + right inspector) — single-pane is overused.' / 'The next project must include a non-trivial backend SIMULATION — a fake auth flow, a synthetic order book, a simulated message bus, or similar.' / 'Use a typography pairing the system has never used (e.g. JetBrains Mono + Crimson Pro). Track the visual_identity field.'
"""


def _load_memory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"projects": [], "ceo_reviews": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_memory(path: Path, memory: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(memory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _summarize_recent(projects: list[dict]) -> str:
    """Compact text summary of recent projects for the CEO prompt."""
    if not projects:
        return "(no projects yet)"
    lines = []
    for p in projects:
        ui = p.get("final_verify_metrics", {}) or {}
        lines.append(
            f"- {p.get('date','?')} {p.get('name','?'):<45} "
            f"c={p.get('complexity_score','?')} "
            f"files={p.get('file_count','?')} loc={p.get('loc','?')} "
            f"cycles={p.get('quality_cycles_used','?')} "
            f"controls={ui.get('interactiveCount','?')} "
            f"pattern={p.get('pattern','?')} "
            f"domain={p.get('domain','?')} "
            f"model={p.get('model_attribution',{}).get('plan','?')}"
        )
    return "\n".join(lines)


def latest_directives(memory: dict, ttl_hours: int = CEO_DIRECTIVE_TTL_HOURS) -> list[str]:
    """Return CEO directives if there's a recent review; empty list otherwise."""
    reviews = memory.get("ceo_reviews", []) or []
    if not reviews:
        return []
    last = reviews[-1]
    issued = last.get("issued_at_unix", 0)
    age_hours = (datetime.now(timezone.utc).timestamp() - issued) / 3600.0
    if age_hours > ttl_hours:
        log.info("CEO directives are %.1fh old (>%.0fh TTL); ignoring.", age_hours, ttl_hours)
        return []
    return last.get("directives", []) or []


def run_ceo_review(memory_log_path: Path = Path("memory_log.json")) -> int:
    """Entry point for the CEO workflow. Returns shell exit code."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        log.error("GITHUB_TOKEN env var is required.")
        return 2
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )

    memory = _load_memory(memory_log_path)
    recent = (memory.get("projects") or [])[-CEO_REVIEW_WINDOW:]

    if len(recent) < 2:
        log.info("Not enough projects yet (%d). Skipping CEO review.", len(recent))
        return 0

    summary = _summarize_recent(recent)
    explored_patterns = [p.get("pattern") for p in recent if p.get("pattern")]
    explored_domains = [p.get("domain") for p in recent if p.get("domain")]
    cs = [p.get("complexity_score", 0) for p in recent]

    user = (
        f"Recent {len(recent)} projects (oldest -> newest):\n{summary}\n\n"
        f"Complexity series: {cs}\n"
        f"Patterns observed: {explored_patterns}\n"
        f"Domains observed: {explored_domains}\n\n"
        "Evaluate this trajectory. Issue strict directives for the NEXT project."
    )

    try:
        text, meta = roles.call_with_fallback(
            client, "ceo",
            system=CEO_SYSTEM, user=user,
            max_tokens=2000, temperature=0.7,
        )
    except roles.AllModelsFailed as e:
        log.error("CEO review failed: every model in chain unavailable. %s", e)
        return 1

    # Parse the CEO output
    text = text.strip()
    if text.startswith("```"):
        import re
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        log.error("CEO output not JSON. First 400 chars:\n%s", text[:400])
        return 1
    review = json.loads(text[s:e + 1])

    record = {
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "issued_at_unix": int(datetime.now(timezone.utc).timestamp()),
        "model": meta.get("model"),
        "verdict": review.get("verdict", "acceptable"),
        "summary": review.get("summary", ""),
        "concerns": review.get("concerns", []) or [],
        "directives": review.get("directives", []) or [],
        "praise": review.get("praise", []) or [],
        "reviewed_project_count": len(recent),
    }
    memory.setdefault("ceo_reviews", []).append(record)
    _save_memory(memory_log_path, memory)

    log.info("CEO verdict: %s | %d directives | %d concerns | model=%s",
             record["verdict"], len(record["directives"]),
             len(record["concerns"]), record["model"])
    for d in record["directives"]:
        log.info("  directive: %s", d)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    sys.exit(run_ceo_review())
