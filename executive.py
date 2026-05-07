"""
executive.py — CEO + CSO meta-watchdogs.

Project Evolution mandate:

CEO (visionary, high-risk tolerance):
    "Why are we making a calculator when we could be writing a framework
    for drone swarms?" Pushes domain shifts, rejects derivative work,
    requires every project to surprise.

CSO — Chief SCIENCE Officer (NOT security, that role is purged):
    Drives experimental edge-cases. Pushes for novel algorithms, physics
    simulations, deep-tech research, mathematical exotica. Loves things
    nobody has tried.

Both roles read memory + failed-build history and write directives the
next architect must obey. They are deliberately allowed to disagree.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

import roles

log = logging.getLogger("brain.executive")

REVIEW_WINDOW = 8
DIRECTIVE_TTL_HOURS = 36


# ─────────────────────── CEO — Visionary ────────────────────────────────

CEO_SYSTEM = """You are the CEO of an autonomous AI software-creation system. You are visionary, high-risk-tolerant, and impatient with safe, derivative work.

Project Evolution mandate: this system was producing repetitive web demos with broken interactivity. That era is over. The new directive is to PUSH BOUNDARIES into unpredictable domains. The architect, engineers, and reviewers are competent but conservative — your job is to drag them out of the local minimum.

DOMAINS YOU CAN PUSH TOWARD (this list is a starting point, not an exhaustive one):
- Browser tools / web-runnable demos (the default — you should bias AGAINST this unless the angle is genuinely fresh)
- Games (chess variants, roguelikes, real-time strategy, abstract puzzles)
- Python tools (cyber forensic utilities, ML experiments, simulation engines, data-pipeline demos)
- 3D scripts (Three.js scenes, OpenSCAD models, raymarchers, generative geometry)
- Robotic logic algorithms (path planning, swarm coordination, sensor fusion)
- Research articles (markdown long-form on novel algorithms, physics, math)
- Business proposals / product design schematics (markdown + ASCII diagrams)
- Generative art systems (shaders, fractals, parametric design)
- Compilers / language interpreters (toy languages, DSLs)
- Audio / DSP / synthesizers
- Physics simulations (cloth, fluid, soft-body, n-body)
- Cryptographic toys (educational ciphers, ZK proofs visualized)
- Information theory / compression
- Cellular automata / artificial life

You receive:
1. RECENT SHIPPED PROJECTS — what reached production
2. RECENT REFUSED BUILDS — what the QA Tester refused to ship; the architect tried and failed
3. CSO directives (if any) from your peer Chief Science Officer

Read all of it. The refusal data is your most important signal — when the architect over-aimed and got blocked, your last directives were probably wrong. Adjust.

Your output is a JSON document. The next plan stage will read your `directives` and obey them. Use this leverage.

OUTPUT — single JSON, no prose, no markdown fences:
{
  "verdict": "thriving" | "acceptable" | "drifting" | "alarming",
  "summary": "1-2 sentence executive judgement",
  "concerns": ["specific, sharp concerns about the trajectory"],
  "directives": ["3-6 imperative instructions for the next project. Each one a single concrete thing. Push toward unpredictable domains."],
  "praise": ["sparingly — what the system did well"]
}

Rules for directives:
- IF recent failures dominate, scale back ambition (simpler patterns, fewer features) so SOMETHING ships.
- IF recent ships are too safe / web-app-shaped / derivative, demand a domain leap (Python tool, 3D, game, document, etc.).
- Never demand the same thing your previous directives demanded if those caused the recent failures.
- Be specific. "Be more creative" is useless. "The next project must be a Python cryptography demo running in Codespaces — no browser UI" is right.
"""


# ─────────────────────── CSO — Chief Science Officer ────────────────────

CSO_SYSTEM = """You are the Chief SCIENCE Officer of an autonomous software-creation system. You are NOT a security officer (that role has been removed). You are the system's experimental edge-case driver — the voice that demands novel algorithms, physics-correct simulations, deep-tech research depth.

You complement the CEO. The CEO pushes for domain leaps. You push for ALGORITHMIC depth within the chosen domain. Where the CEO might say "build a Python tool", you'd add "make it a constraint solver using DPLL with conflict-driven clause learning, not a glorified for-loop."

You receive the same data as the CEO: shipped projects + refused builds. Your job: identify whether recent work is intellectually substantive or whether the architect is hiding shallow ideas behind ambitious-sounding labels.

Areas you care about:
- Algorithmic novelty (does this implement something with depth, or is it a wrapper?)
- Mathematical correctness (correct numerical methods? correct probability? correct physics?)
- Information-theoretic interest (is there compression, entropy, or Bayesian inference at play?)
- Deep-tech ambition (consensus protocols, distributed systems, formal verification, DSP)
- Edge-case rigor (what happens at the boundary, the singular point, the empty input?)

Output schema same as CEO:
{
  "verdict": "thriving" | "acceptable" | "drifting" | "alarming",
  "summary": "1-2 sentences",
  "concerns": ["scientific / algorithmic concerns"],
  "directives": ["specific algorithmic / scientific demands"],
  "praise": []
}

Be sharp. Be curious. Demand novelty.
"""


# ─────────────────────── Helpers ────────────────────────────────────────

def _load_memory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"projects": [], "ceo_reviews": [], "cso_reviews": [], "failed_builds": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_memory(path: Path, memory: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(memory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _summarize_recent(projects: list[dict]) -> str:
    if not projects:
        return "(no projects yet)"
    lines = []
    for p in projects:
        ui = p.get("final_verify_metrics", {}) or {}
        qa = p.get("qa_review") or {}
        lines.append(
            f"- {p.get('date','?')} {p.get('name','?'):<45} "
            f"c={p.get('complexity_score','?')} "
            f"type={p.get('project_type','web')} "
            f"qa={qa.get('verdict','-')} "
            f"pattern={p.get('pattern','?')} "
            f"domain={p.get('domain','?')}"
        )
    return "\n".join(lines)


def _summarize_failures(failed_builds: list[dict]) -> str:
    if not failed_builds:
        return "(no refused builds in window)"
    lines = ["REFUSED builds (project generated, refused before publish):"]
    for f in failed_builds:
        dead = len(f.get("qa_dead_controls") or [])
        miss = len(f.get("qa_missing_features") or [])
        lines.append(
            f"- {f.get('date','?')} \"{f.get('plan_name','?')}\" "
            f"c={f.get('plan_complexity','?')} "
            f"pattern={f.get('plan_pattern','?')} "
            f"domain={f.get('plan_domain','?')} "
            f"-> {f.get('refusal_stage','?')}: dead={dead} missing={miss}"
        )
    return "\n".join(lines)


def latest_directives(memory: dict, key: str, ttl_hours: int = DIRECTIVE_TTL_HOURS) -> list[str]:
    reviews = memory.get(key, []) or []
    if not reviews:
        return []
    last = reviews[-1]
    issued = last.get("issued_at_unix", 0)
    age_hours = (datetime.now(timezone.utc).timestamp() - issued) / 3600.0
    if age_hours > ttl_hours:
        log.info("%s directives are %.1fh old (>%.0fh TTL); ignoring.", key, age_hours, ttl_hours)
        return []
    return last.get("directives", []) or []


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError(f"No JSON object found. First 400 chars:\n{text[:400]}")
    return json.loads(text[s:e + 1])


def _run_review(role: str, system_prompt: str, memory_log_path: Path,
                review_key: str, label: str) -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        log.error("GITHUB_TOKEN env var is required.")
        return 2
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=token,
    )

    memory = _load_memory(memory_log_path)
    recent = (memory.get("projects") or [])[-REVIEW_WINDOW:]
    if len(recent) < 2:
        log.info("Not enough projects yet (%d). Skipping %s review.", len(recent), label)
        return 0

    summary = _summarize_recent(recent)
    failed = (memory.get("failed_builds") or [])[-REVIEW_WINDOW:]
    failures_summary = _summarize_failures(failed)

    user = (
        f"Recent {len(recent)} SHIPPED projects (oldest -> newest):\n{summary}\n\n"
        f"{failures_summary}\n\n"
        "Issue strict directives for the NEXT project."
    )

    try:
        text, meta = roles.call_with_fallback(
            client, role,
            system=system_prompt, user=user,
            max_tokens=2200, temperature=0.7,
        )
    except roles.AllModelsFailed as e:
        log.error("%s review failed: %s", label, e)
        return 1

    try:
        review = _parse_json(text)
    except Exception as e:
        log.error("%s output not parseable: %s\n%s", label, e, text[:400])
        return 1

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
    memory.setdefault(review_key, []).append(record)
    _save_memory(memory_log_path, memory)

    log.info("%s verdict: %s | %d directives | model=%s",
             label, record["verdict"], len(record["directives"]), record["model"])
    for d in record["directives"]:
        log.info("  %s directive: %s", label, d)
    return 0


def run_ceo_review(memory_log_path: Path = Path("memory_log.json")) -> int:
    return _run_review("ceo", CEO_SYSTEM, memory_log_path, "ceo_reviews", "CEO")


def run_cso_review(memory_log_path: Path = Path("memory_log.json")) -> int:
    return _run_review("cso", CSO_SYSTEM, memory_log_path, "cso_reviews", "CSO")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    mode = sys.argv[1] if len(sys.argv) > 1 else "ceo"
    if mode == "cso":
        sys.exit(run_cso_review())
    sys.exit(run_ceo_review())
