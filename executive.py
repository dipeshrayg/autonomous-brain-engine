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
from pipeline import _type_diversity_summary

log = logging.getLogger("brain.executive")

REVIEW_WINDOW = 8
DIRECTIVE_TTL_HOURS = 36


# ─────────────────────── CEO — Visionary ────────────────────────────────

CEO_SYSTEM = """You are the CEO of an autonomous AI software-creation system. You are visionary, high-risk-tolerant, and impatient with safe, derivative work.

ENTERPRISE MANDATE (overriding when enterprise mode is active): The system is now selling to an enterprise procurement board. Your directives MUST push toward product-grade B2B/SaaS deliverables — multi-view SaaS apps, analytics/observability dashboards, internal admin consoles, system & data architecture showcases, API products, and developer-tooling products, across credible business domains (fintech, healthtech, devops, security/SOC, supply-chain, HR analytics, data infrastructure, B2B CRM). Each must look like a real funded product with a design system and realistic synthetic data. Do NOT direct toward toys: no generative art, shaders, games, canvas doodles, or single-gimmick pages. Demand a named product with a clear value proposition a CFO would understand.

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

TYPE DIVERSITY MANDATE:
The system MUST NOT build the same project_type twice in a row. Read the TYPE DIVERSITY REPORT to see counts, ceilings, and recommended next types. Your directives MUST specify a different project_type than the last shipped project.

Available types (NEVER-TRIED ones have the most headroom — push toward them aggressively):
  web_interactive, web_3d, python_tool, document, generative_art, game_web,
  shader_art     — GLSL fragment shaders, pure WebGL, no Three.js. Reaction-diffusion, raymarched SDFs, fluid sims.
  data_viz       — Python heavy data work: matplotlib/plotly/altair/rich TUI + embedded SVG output in index.html.
  typescript_app — Modern JS app using ES module imports from esm.sh CDN. IMPORTANT: files are .js and .html only,
                   NOT .ts — GitHub Pages cannot compile TypeScript. The architect must use plain .js files with
                   <script type="module"> and import libraries like d3, vue, or chart.js from https://esm.sh/.
  cli_tool       — Rust or Go CLI utility + Codespaces devcontainer + animated terminal showcase index.html.

If shader_art, data_viz, typescript_app, or cli_tool are untried — demand one of them. But only demand
typescript_app if you understand: the architect must produce .js files, NOT .ts files.

CRITICAL SELF-HEALING RULE — TYPE BANS:
If a project_type has failed 3 or more times in a row (shown as BANNED in the diversity report), you MUST NOT demand that type again. The system cannot build it successfully right now. Pivot to a DIFFERENT type that has a proven track record of shipping. If multiple types are banned, fall back to types that have shipped before (web_interactive, python_tool, document, game_web, etc.). The goal is to SHIP SOMETHING — a working project in a different type is infinitely better than another failed attempt at a broken type. You can revisit banned types later after a successful ship resets the failure counter.

HUMAN USABILITY MANDATE — this is your most important quality signal:
A project that ships but cannot be USED by a human visiting the GitHub Pages URL is WORSE than a refused build. It pollutes the portfolio. Watch for these in shipped projects:
- python_tool with QA verdict "shippable" but NO JavaScript computation in index.html — the page is a brochure, not a tool.
- Any project where the "partially_usable" verdict lists an "Analyze", "Run", "Compute", or "Visualize" button as dead.
- Projects that look impressive from the description but the actual page is a blank canvas or static description.

If you see these in recent ships, issue a directive: "The next python_tool MUST implement its core algorithm fully in JavaScript in index.html — no exceptions. A python_tool that requires Python to do anything useful is a failure."

Rules for directives:
- IF recent failures dominate, scale back ambition (simpler patterns, fewer features) so SOMETHING ships. CHANGE THE TYPE — do not keep demanding the same failing type.
- IF recent ships are too safe / web-app-shaped / derivative, demand a domain leap (Python tool, 3D, game, document, etc.).
- Never demand the same thing your previous directives demanded if those caused the recent failures.
- Be specific. "Be more creative" is useless. "The next project must be a Python cryptography tool — and index.html must run the cipher in JavaScript so a human can use it without installing Python" is right.
- ALWAYS specify which project_type to use next. Check the type diversity report and pick one that's NOT BANNED and underrepresented.
- If you see 3+ consecutive failures of the same type, your #1 priority is pivoting away from that type.
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

Return valid JSON matching this schema:
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

    diversity = _type_diversity_summary(memory)
    user = (
        f"Recent {len(recent)} SHIPPED projects (oldest -> newest):\n{summary}\n\n"
        f"{failures_summary}\n\n"
        f"{diversity}\n\n"
        "Issue strict directives for the NEXT project. "
        "You MUST specify which project_type to use, based on the diversity report above."
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

    # Mirror the review to Supabase (best-effort; never blocks).
    try:
        import supabase_sync
        supabase_sync.sync_review(review_key, record)
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase review sync skipped: %s", e)

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
