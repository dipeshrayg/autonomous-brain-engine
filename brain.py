#!/usr/bin/env python3
"""
brain.py - Master orchestrator for the daily autonomous build pipeline.

Architecture (one file imports the modules; the heavy lifting lives there):
    pipeline.py  - LLM stages: plan -> implement -> critique -> fix -> polish
    verifier.py  - Headless Chrome verification (Playwright)
    dashboard.py - Renders README.md + index.html from memory_log

Daily flow:
    1. Idempotency check (skip on schedule re-fires).
    2. Plan (with hard advancement gates).
    3. Implement each planned file in its own LLM call.
    4. Quality loop:    materialize -> verify (browser) -> critique (LLM)
                        -> fix (LLM) -> repeat. Up to MAX_QUALITY_CYCLES.
    5. Polish pass (visuals, controls, edge cases).
    6. Final verify; one last fix if anything regressed.
    7. Publish to a fresh public GitHub repo + enable Pages.
    8. Wait for Pages to go live; record memory; render dashboard.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from github import Github, GithubException
from openai import OpenAI

import pipeline
import verifier
import dashboard
import executive
# security_officer removed in Project Evolution; CSO is now Chief Science Officer
# in executive.py with role label "cso".

# ─────────────────────── Configuration ──────────────────────────────────

GH_MODELS_BASE_URL = "https://models.inference.ai.azure.com"

MAX_QUALITY_CYCLES = 8        # critique+fix iterations
TEST_TIMEOUT_SECONDS = 300
MAX_PROJECTS_PER_DAY = 5      # cap for runaway-loop protection
MIN_HOURS_BETWEEN_PROJECTS = 5  # 5h spacing per user spec; manual_dispatch overrides

MEMORY_LOG_PATH = Path("memory_log.json")
WORKSPACE = Path("workspace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("brain")

# ─────────────────────── Memory ─────────────────────────────────────────

def load_memory() -> dict[str, Any]:
    if not MEMORY_LOG_PATH.exists():
        return {"projects": [], "complexity_trajectory": [], "concepts_explored": []}
    with MEMORY_LOG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(memory: dict[str, Any]) -> None:
    with MEMORY_LOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)
        f.write("\n")


def record_failure(memory: dict[str, Any], plan: dict | None, stage: str, reason: str,
                   qa_report: dict | None = None,
                   security_report: dict | None = None,
                   verify_result: dict | None = None) -> None:
    """
    Append a refused-build record to memory_log.failed_builds[]. The CEO reads
    this list on its next review and adjusts strategy accordingly. Without
    this, the CEO only sees what shipped — and keeps demanding the same
    ambitious patterns that the QA gate is rejecting.
    """
    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "attempted_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attempted_at_unix": int(now.timestamp()),
        "date": now.strftime("%Y-%m-%d"),
        "refusal_stage": stage,
        "refusal_reason": reason,
    }
    if plan:
        record.update({
            "plan_name": plan.get("name", "(unknown)"),
            "plan_language": plan.get("language", "?"),
            "plan_complexity": int(plan.get("complexity_score", 0)),
            "plan_pattern": plan.get("pattern", "?"),
            "plan_domain": plan.get("domain", "?"),
            "plan_files_count": len(plan.get("files", [])),
            "project_type": plan.get("project_type", "unknown"),
        })
    if qa_report:
        record["qa_verdict"] = qa_report.get("verdict")
        record["qa_dead_controls"] = [
            {"control": d.get("control"), "expected": d.get("expected")}
            for d in (qa_report.get("dead_controls") or [])[:5]
            if isinstance(d, dict)
        ]
        record["qa_missing_features"] = [
            {"feature": f.get("feature")}
            for f in (qa_report.get("missing_features") or [])[:5]
            if isinstance(f, dict)
        ]
    if security_report:
        record["security_verdict"] = security_report.get("verdict")
        record["security_blocking_count"] = sum(
            1 for f in (security_report.get("findings") or [])
            if isinstance(f, dict) and f.get("severity") in ("critical", "high")
        )
    if verify_result:
        metrics = verify_result.get("metrics", {}) or {}
        interaction = metrics.get("interaction") or {}
        record["final_interaction"] = {
            "tested": interaction.get("tested"),
            "live": interaction.get("live_count"),
            "dead": len(interaction.get("dead_controls") or []),
        }
        record["final_interactive_count"] = metrics.get("interactiveCount")
    memory.setdefault("failed_builds", []).append(record)
    save_memory(memory)
    log.info("Recorded refused build to memory_log.failed_builds[]: %s @ %s (reason=%s)",
             record.get("plan_name", "?"), stage, reason[:120])


def _last_project_unix(memory: dict[str, Any]) -> float | None:
    """Unix timestamp of the most-recent project's completion, or None."""
    projects = memory.get("projects", []) or []
    if not projects:
        return None
    last = projects[-1]
    if "completed_at_unix" in last:
        return float(last["completed_at_unix"])
    # Backwards compat: parse the date string and assume mid-day UTC.
    date = last.get("date")
    if not date:
        return None
    try:
        dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=12)
        return dt.timestamp()
    except ValueError:
        return None


def append_record(memory: dict[str, Any], plan: dict, files: dict[str, str],
                  repo_url: str, pages_url: str, cycles: int,
                  verify_result: dict, model_per_file: dict[str, str],
                  ceo_directives: list[str] | None,
                  qa_report: dict | None = None) -> None:
    now = datetime.now(timezone.utc)
    record = {
        "date": now.strftime("%Y-%m-%d"),
        "completed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at_unix": int(now.timestamp()),
        "name": plan["name"],
        "repo_url": repo_url,
        "pages_url": pages_url,
        "language": plan["language"],
        "project_type": plan.get("project_type", "web_interactive"),
        "tech_stack": plan.get("tech_stack", []),
        "complexity_score": int(plan.get("complexity_score", 0)),
        "concepts_demonstrated": plan.get("concepts_demonstrated", []),
        "novel_concepts": plan.get("novel_concepts", []),
        "advancement_axis": plan.get("advancement_axis", ""),
        "pattern": plan.get("pattern", ""),
        "domain": plan.get("domain", ""),
        "visual_identity": plan.get("visual_identity", ""),
        "safety_notes": plan.get("safety_notes", ""),
        "file_count": len(files),
        "loc": sum(c.count("\n") + 1 for c in files.values()),
        "quality_cycles_used": cycles,
        "final_verify_metrics": verify_result.get("metrics", {}),
        # Multi-model attribution
        "model_attribution": {
            "plan_judge": plan.get("__model__", "?"),
            "plan_candidates": plan.get("__candidate_models__", []),
            "candidates_considered": plan.get("__candidates_considered__", 1),
            "implement_per_file": model_per_file,
        },
        "ceo_directives_followed": list(ceo_directives or []),
        "qa_review": (
            {
                "verdict": qa_report.get("verdict"),
                "summary": qa_report.get("summary"),
                "model": qa_report.get("__model__"),
                "dead_controls_count": len(qa_report.get("dead_controls") or []),
                "missing_features_count": len(qa_report.get("missing_features") or []),
                "dead_controls": qa_report.get("dead_controls") or [],
                "missing_features": qa_report.get("missing_features") or [],
            }
            if qa_report else None
        ),
    }
    memory.setdefault("projects", []).append(record)
    memory.setdefault("complexity_trajectory", []).append(record["complexity_score"])
    explored = memory.setdefault("concepts_explored", [])
    for c in (plan.get("concepts_demonstrated") or []):
        if c not in explored:
            explored.append(c)
    if record["pattern"]:
        memory.setdefault("patterns_used", []).append(record["pattern"])
    if record["domain"]:
        memory.setdefault("domains_used", []).append(record["domain"])
    save_memory(memory)
    log.info("Memory updated: project #%d (pattern=%s, domain=%s, plan_model=%s).",
             len(memory["projects"]), record["pattern"], record["domain"],
             record["model_attribution"]["plan_judge"])


# ─────────────────────── Workspace ──────────────────────────────────────

def materialize(files: dict[str, str], target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for path, content in files.items():
        dest = target / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    log.info("Materialized %d file(s) into %s", len(files), target)


def merge_updates(files: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    out = dict(files)
    for path, content in updates.items():
        out[path] = content
    return out


# ─────────────────────── Verify (web vs fallback) ───────────────────────

def verify_project(plan: dict, target: Path) -> dict[str, Any]:
    """Route verification by project_type. Web → Playwright; Python → run-it; Document → structure-check."""
    pt = plan.get("project_type", "web_interactive")
    # All browser-rendered types — verified with Playwright
    web_types = {
        "web_interactive", "web_3d", "game_web", "generative_art",
        "shader_art", "typescript_app",
    }
    # Python-executed types
    python_types = {"python_tool", "data_viz"}
    # CLI tools need build step — verify the index.html showcase + check build files exist
    cli_types = {"cli_tool"}

    if pt in web_types:
        try:
            return verifier.verify_web(target, timeout=30, project_type=pt)
        except Exception as e:
            log.exception("Browser verify crashed.")
            return {
                "errors": [f"verifier exception: {e}"],
                "issues": [f"Browser verifier crashed: {e}. Check that index.html parses."],
                "metrics": {},
                "screenshot": None,
            }
    if pt in python_types:
        try:
            return verifier.verify_python(target, plan, timeout=60)
        except Exception as e:
            log.exception("Python verify crashed.")
            return {"errors": [f"verifier exception: {e}"], "issues": [], "metrics": {}, "screenshot": None}
    if pt in cli_types:
        try:
            # Verify index.html showcase loads + check source files exist
            web_result = verifier.verify_web(target, timeout=30, project_type=pt)
            # Also check that at least one source file (*.rs or *.go) exists
            src_files = list(target.rglob("*.rs")) + list(target.rglob("*.go"))
            if not src_files:
                web_result.setdefault("issues", []).append(
                    "cli_tool: no .rs or .go source files found. Include the actual source."
                )
            return web_result
        except Exception as e:
            log.exception("CLI verify crashed.")
            return {"errors": [f"verifier exception: {e}"], "issues": [], "metrics": {}, "screenshot": None}
    if pt == "document":
        try:
            return verifier.verify_document(target, plan)
        except Exception as e:
            log.exception("Document verify crashed.")
            return {"errors": [f"verifier exception: {e}"], "issues": [], "metrics": {}, "screenshot": None}

    # Unknown type — default to web
    return verifier.verify_web(target, timeout=30)


# ─────────────────────── Publish (PyGithub + git CLI) ───────────────────

def date_prefixed_name(name: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{today}-{name}"[:99]


def run(cmd: str, cwd: Path, timeout: int = 120) -> tuple[int, str]:
    log.info("$ %s   (cwd=%s)", cmd, cwd)
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(cwd),
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s\n{e.stdout or ''}\n{e.stderr or ''}"


def publish(plan: dict, src: Path, gh_token: str) -> tuple[str, str, str]:
    """Returns (repo_url, pages_url, owner_login)."""
    g = Github(gh_token)
    user = g.get_user()
    base = date_prefixed_name(plan["name"])
    repo_name = base
    repo = None
    for attempt in range(1, 11):
        log.info("Creating GitHub repo %s/%s (attempt %d)", user.login, repo_name, attempt)
        try:
            repo = user.create_repo(
                name=repo_name,
                description=plan["description"][:350],
                private=False,
                has_issues=True,
                has_wiki=False,
                auto_init=False,
            )
            break
        except GithubException as e:
            if e.status == 422 and "name already exists" in str(e):
                repo_name = f"{base[:90]}-v{attempt + 1}"
                log.warning("Repo name collision; retrying with %s", repo_name)
                continue
            raise RuntimeError(f"create_repo failed: {e}") from e
    if repo is None:
        raise RuntimeError(f"Could not find a free repo name after 10 attempts (base={base})")

    # Don't push the verifier's screenshot artefact.
    artefact = src / ".verify-screenshot.png"
    if artefact.exists():
        artefact.unlink()

    remote = f"https://x-access-token:{gh_token}@github.com/{user.login}/{repo_name}.git"
    for cmd in [
        "git init -b main",
        'git config user.name "autonomous-brain[bot]"',
        'git config user.email "autonomous-brain@users.noreply.github.com"',
        "git add .",
        f'git commit -m "Initial commit: {plan["name"]} (complexity {plan["complexity_score"]})"',
        f"git remote add origin {remote}",
        "git push -u origin main",
    ]:
        rc, out = run(cmd, src, 120)
        if rc != 0:
            raise RuntimeError(f"git step failed `{cmd}`:\n{out}")

    # All projects get Pages — every type produces an index.html visual showcase
    pages_url = enable_pages(repo.full_name, repo.owner.login, repo.name, gh_token)
    return repo.html_url, pages_url, user.login


def enable_pages(full_name: str, owner: str, name: str, gh_token: str) -> str:
    log.info("Enabling GitHub Pages for %s", full_name)
    r = requests.post(
        f"https://api.github.com/repos/{full_name}/pages",
        headers={
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"source": {"branch": "main", "path": "/"}},
        timeout=30,
    )
    if r.status_code not in (201, 409):
        log.warning("Pages enable returned %d: %s", r.status_code, r.text[:300])
        return ""
    return f"https://{owner}.github.io/{name}/"


# ─────────────────────── Quality loop ───────────────────────────────────

def implement_all(client: OpenAI, plan: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Generate every file in the plan, in order. Returns (files, model_per_file)."""
    files: dict[str, str] = {}
    model_per_file: dict[str, str] = {}
    for fs in plan["files"]:
        log.info("IMPLEMENT %s", fs["path"])
        path, content, meta = pipeline.stage_implement(client, plan, fs, files)
        files[path] = content
        model_per_file[path] = meta.get("model", "?")
    log.info("Implemented %d file(s) totalling %d chars.",
             len(files), sum(len(c) for c in files.values()))
    return files, model_per_file


def quality_loop(client: OpenAI, plan: dict, files: dict[str, str],
                 target: Path) -> tuple[dict[str, str], int, dict]:
    """Verify -> critique-conference -> fix; loop until clean or budget exhausted."""
    materialize(files, target)
    verify = verify_project(plan, target)
    cycles = 0
    last_verify = verify

    for cycle in range(1, MAX_QUALITY_CYCLES + 1):
        log.info("CRITIQUE conference cycle %d (browser issues=%d, errors=%d)",
                 cycle, len(verify.get("issues", [])), len(verify.get("errors", [])))
        critique = pipeline.stage_critique(client, plan, files, verify)
        verdict = critique.get("verdict", "fix")
        must_fix = critique.get("must_fix") or []
        reviews = critique.get("_reviews", [])
        log.info("Critique conference verdict=%s, merged must_fix=%d, reviewers=%s",
                 verdict, len(must_fix),
                 [f"{r.get('model')}:{r.get('verdict')}" for r in reviews])

        all_issues: list[str] = []
        all_issues.extend(verify.get("errors", []))
        all_issues.extend(verify.get("issues", []))
        for item in must_fix:
            if isinstance(item, dict):
                f = item.get("file", "")
                src = item.get("raised_by", "?")
                msg = f"{item.get('issue', '')}  -- suggestion: {item.get('suggestion', '')}"
                all_issues.append(f"[{f}] (from {src}) {msg}")

        if verdict == "ship" and not all_issues:
            log.info("Critique says SHIP and zero issues - quality loop done.")
            return files, cycles, verify

        if not all_issues:
            log.info("Critique non-ship but produced no must_fix items; treating as ship.")
            return files, cycles, verify

        log.info("FIX cycle %d - %d issue(s) to address.", cycle, len(all_issues))
        updates = pipeline.stage_fix(client, plan, files, all_issues)
        if not updates:
            log.warning("Fix returned zero updates; giving up on this cycle.")
            break

        files = merge_updates(files, updates)
        materialize(files, target)
        verify = verify_project(plan, target)
        last_verify = verify
        cycles = cycle

        if not verify.get("errors") and not verify.get("issues"):
            log.info("Browser verify is clean after cycle %d.", cycle)
            return files, cycles, verify

    log.warning("Quality budget (%d cycles) exhausted; proceeding to polish anyway.", MAX_QUALITY_CYCLES)
    return files, cycles, last_verify


# ─────────────────────── Main ───────────────────────────────────────────

def main() -> int:
    models_token = os.environ.get("GITHUB_TOKEN")
    gh_token = os.environ.get("GH_PAT")
    if not models_token or not gh_token:
        log.error("GITHUB_TOKEN and GH_PAT env vars are required.")
        return 2

    memory = load_memory()

    # Idempotency for scheduled / watchdog runs:
    #   - Skip if today already has MAX_PROJECTS_PER_DAY projects (hard cap).
    #   - Skip if the most-recent project is < MIN_HOURS_BETWEEN_PROJECTS old.
    # Manual workflow_dispatch overrides both checks so the user can force
    # extra creations on demand.
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    today_count = sum(1 for p in memory.get("projects", []) if p.get("date") == today)

    if event == "schedule":
        if today_count >= MAX_PROJECTS_PER_DAY:
            log.info("Today (%s) has %d/%d projects; scheduled run skipping.",
                     today, today_count, MAX_PROJECTS_PER_DAY)
            return 0
        # Spacing check
        last_ts = _last_project_unix(memory)
        if last_ts is not None:
            hours_since = (now.timestamp() - last_ts) / 3600.0
            if hours_since < MIN_HOURS_BETWEEN_PROJECTS:
                log.info("Last project was %.1fh ago; need >=%dh between projects. Skipping.",
                         hours_since, MIN_HOURS_BETWEEN_PROJECTS)
                return 0
            log.info("Last project was %.1fh ago. Proceeding.", hours_since)

    log.info("Today (%s) has %d/%d projects so far. Building project #%d.",
             today, today_count, MAX_PROJECTS_PER_DAY, today_count + 1)

    # ── Expansion mode: activate when CEO says "alarming", deactivate on recovery ──
    ceo_reviews = memory.get("ceo_reviews", [])
    if ceo_reviews:
        latest_ceo_verdict = ceo_reviews[-1].get("verdict", "acceptable")
        if latest_ceo_verdict == "alarming" and not memory.get("expansion_mode"):
            memory["expansion_mode"] = True
            memory["expansion_mode_since"] = datetime.now(timezone.utc).isoformat()
            save_memory(memory)
            log.warning(
                "EXPANSION MODE ACTIVATED: CEO verdict=alarming. "
                "Unlocking 8 expansion project types (saas_landing, database_showcase, "
                "research_showcase, social_toolkit, ai_concept, creative_tool, "
                "edu_platform, prank_entertainment) and resetting all type bans."
            )
        elif latest_ceo_verdict in ("thriving", "acceptable") and memory.get("expansion_mode"):
            # Deactivate once system has recovered and CEO is happy
            expansion_shipped = sum(
                1 for p in memory.get("projects", [])
                if p.get("project_type") in pipeline.EXPANSION_TYPES
            )
            if expansion_shipped >= 3:
                memory["expansion_mode"] = False
                save_memory(memory)
                log.info(
                    "Expansion mode deactivated: CEO verdict=%s and %d expansion "
                    "projects shipped. Returning to standard types.",
                    latest_ceo_verdict, expansion_shipped
                )

    client = OpenAI(base_url=GH_MODELS_BASE_URL, api_key=models_token)
    ceo_directives: list[str] = []  # initialise before try so except block can reference it

    try:
        # CEO directives — visionary push for new domains.
        ceo_directives = executive.latest_directives(memory, "ceo_reviews")
        if ceo_directives:
            log.info("CEO has issued %d active directive(s).", len(ceo_directives))
            for d in ceo_directives:
                log.info("  CEO: %s", d)

        # CSO directives — Chief Science Officer (algorithmic depth, novelty).
        cso_directives = executive.latest_directives(memory, "cso_reviews")
        if cso_directives:
            log.info("CSO has issued %d active science directive(s).", len(cso_directives))
            for d in cso_directives:
                log.info("  CSO: %s", d)

        # 1. PLAN — Architect Conference
        log.info("════════ STAGE 1: ARCHITECT CONFERENCE ════════")
        plan = pipeline.stage_plan(client, memory,
                                   ceo_directives=ceo_directives,
                                   cso_directives=cso_directives)

        # 2. IMPLEMENT
        log.info("════════ STAGE 2: IMPLEMENT (Engineer role) ════════")
        files, impl_meta = implement_all(client, plan)

        # 3+4. QUALITY LOOP (verify ↔ critique ↔ fix)
        log.info("════════ STAGE 3+4: QUALITY LOOP (Reviewer conference + Fixer) ════════")
        files, cycles_used, _ = quality_loop(client, plan, files, WORKSPACE)

        # 5. POLISH (with rollback safety)
        log.info("════════ STAGE 5: POLISH (Polisher role) ════════")
        pre_polish_files = dict(files)
        pre_polish_verify = verify_project(plan, WORKSPACE)
        pre_polish_problem_count = (
            len(pre_polish_verify.get("errors", []))
            + len(pre_polish_verify.get("issues", []))
        )
        polish_updates = pipeline.stage_polish(client, plan, files)
        if polish_updates:
            files = merge_updates(files, polish_updates)
            materialize(files, WORKSPACE)

        # 6. FINAL VERIFY
        log.info("════════ STAGE 6: FINAL VERIFY ════════")
        final_verify = verify_project(plan, WORKSPACE)
        post_polish_problem_count = (
            len(final_verify.get("errors", []))
            + len(final_verify.get("issues", []))
        )
        if post_polish_problem_count > pre_polish_problem_count:
            log.warning(
                "Polish regressed quality (problems %d -> %d); reverting to pre-polish files.",
                pre_polish_problem_count, post_polish_problem_count,
            )
            files = pre_polish_files
            materialize(files, WORKSPACE)
            final_verify = pre_polish_verify
        elif final_verify.get("errors") or final_verify.get("issues"):
            log.warning("Polish kept quality the same but issues remain; running one fix pass.")
            pre_postfix_files = dict(files)
            pre_postfix_problems = (
                len(final_verify.get("errors", []))
                + len(final_verify.get("issues", []))
            )
            issues = (final_verify.get("errors") or []) + (final_verify.get("issues") or [])
            updates = pipeline.stage_fix(client, plan, files, issues)
            if updates:
                files = merge_updates(files, updates)
                materialize(files, WORKSPACE)
                final_verify = verify_project(plan, WORKSPACE)
                post_postfix_problems = (
                    len(final_verify.get("errors", []))
                    + len(final_verify.get("issues", []))
                )
                if post_postfix_problems > pre_postfix_problems:
                    log.warning(
                        "Post-polish fix REGRESSED (%d -> %d problems); reverting.",
                        pre_postfix_problems, post_postfix_problems,
                    )
                    files = pre_postfix_files
                    materialize(files, WORKSPACE)
                    final_verify = verify_project(plan, WORKSPACE)

        # 6.4 QA REVIEW — does the project ACTUALLY DO what the plan promised?
        # The mechanical interaction test in verifier already reports dead
        # controls; the QA Tester role (gpt-4o) layers a usability judgement on
        # top, including "promised feature missing entirely". Up to 3 fix rounds.
        log.info("════════ STAGE 6.4: QA REVIEW (Tester role) ════════")
        qa_report = pipeline.stage_qa_review(client, plan, files, final_verify)
        qa_findings_to_record = qa_report

        # The QA fixer gets a crack at usability problems regardless of the
        # 'verdict' label: if there are concrete dead controls or missing
        # features, fix them. Verdict alone (non_functional vs partially_usable)
        # depends on how the QA Tester drew the line — but a dead Save button
        # is dead either way, and shouldn't ship.
        def _qa_should_run(qa_rep: dict, verify: dict) -> bool:
            if qa_rep.get("verdict") == "non_functional":
                return True
            if qa_rep.get("dead_controls") or qa_rep.get("missing_features"):
                return True
            for issue in (verify.get("issues") or []):
                low = issue.lower()
                if "blank" in low or "runaway" in low or "empty" in low or "zero" in low:
                    return True
            return False

        MAX_QA_FIX_ROUNDS = 3
        qa_round = 0
        while _qa_should_run(qa_report, final_verify) and qa_round < MAX_QA_FIX_ROUNDS:
            qa_round += 1
            dead = qa_report.get("dead_controls") or []
            missing = qa_report.get("missing_features") or []
            verifier_blockers = [
                i for i in (final_verify.get("issues") or [])
                if any(k in i.lower() for k in ("blank", "runaway", "empty", "zero"))
            ]
            log.warning(
                "QA round %d/%d: %d dead, %d missing, %d verifier blocker(s) — qa_fixer (gpt-4o).",
                qa_round, MAX_QA_FIX_ROUNDS,
                len(dead), len(missing), len(verifier_blockers),
            )
            qa_issues: list[str] = []
            for d in dead:
                if isinstance(d, dict):
                    qa_issues.append(
                        f"[dead-control] {d.get('control','?')} should {d.get('expected','do something')} "
                        f"but {d.get('actual','does nothing')}. Fix: {d.get('fix','')}"
                    )
            for f in missing:
                if isinstance(f, dict):
                    qa_issues.append(
                        f"[missing-feature] {f.get('feature','?')} promised in plan but not "
                        f"implemented ({f.get('why_missing','?')}). Fix: {f.get('fix','')}"
                    )
            for vb in verifier_blockers:
                qa_issues.append(f"[render] {vb}")

            if not qa_issues:
                log.warning("QA flagged but no specific issues — escaping loop.")
                break
            updates = pipeline.stage_qa_fix(client, plan, files, qa_issues)
            if not updates:
                log.warning("QA fixer returned no updates; aborting QA loop.")
                break
            files = merge_updates(files, updates)
            materialize(files, WORKSPACE)
            final_verify = verify_project(plan, WORKSPACE)
            qa_report = pipeline.stage_qa_review(client, plan, files, final_verify)
            qa_findings_to_record = qa_report

        # Final hard-quality gate: refuse to publish if QA couldn't fix the
        # fundamentals after its rounds. partially_usable with a few residual
        # dead controls IS allowed to ship — the QA badge surfaces the state
        # to the visitor — but non_functional or fundamental verifier
        # blockers (blank canvas, page errors) are hard refusals.
        #
        # ── SHIP-FIRST QUALITY GATE ──────────────────────────────────────────
        # User directive: a real, interactive project in the deliveries list beats an
        # empty portfolio. After the QA fix rounds, the project SHIPS unless it is
        # genuinely dead-on-arrival for a human visitor.
        #
        # SHIPS:  shippable, partially_usable, and even a non_functional verdict whose
        #         page still loads and renders interactive content (the QA Tester is
        #         deliberately conservative and over-reports non_functional). All of
        #         these get a 🧪 "partial" badge when not fully shippable so visitors
        #         see the honest state.
        # REFUSES (the only hard stop): the page is genuinely broken — real uncaught
        #         JS page errors that break rendering, OR an essentially empty body.
        #         These are objective mechanical failures, not the QA Tester's opinion.
        #
        # The old keyword scan (blank/runaway/empty/zero in verifier "issues") is gone:
        # it produced false positives for canvas/WebGL/tool/expansion-type UIs and was
        # the single biggest reason real projects never shipped.
        page_errors = final_verify.get("errors") or []
        body_empty = any(
            "essentially empty" in str(i).lower() or "250 chars" in str(i).lower()
            for i in (final_verify.get("issues") or [])
        )
        genuinely_broken = bool(page_errors) or body_empty
        if genuinely_broken:
            log.error("Final quality gate: page is genuinely broken — refusing to publish.")
            for hb in (page_errors[:5] or []):
                log.error("  [PAGE-ERROR] %s", str(hb)[:180])
            if body_empty:
                log.error("  [EMPTY-BODY] page body has almost no rendered HTML.")
            record_failure(
                memory, plan,
                stage="qa_gate",
                reason=(
                    f"Page genuinely broken after {qa_round} QA round(s). "
                    f"verdict={qa_report.get('verdict')}, "
                    f"{len(page_errors)} page error(s), body_empty={body_empty}."
                ),
                qa_report=qa_report,
                verify_result=final_verify,
            )
            # NON-HALTING: recorded, but exit 0 so the run stays green.
            save_memory(memory)
            log.info("Build refused (page broken) and recorded. Exiting 0 (non-halting mode).")
            return 0
        # Everything else ships. Surface partial state honestly via the badge.
        if qa_report.get("verdict") != "shippable":
            residual_dead = len(qa_report.get("dead_controls") or [])
            log.warning(
                "SHIP-FIRST: publishing despite QA verdict=%s (%d residual dead control(s)). "
                "Card will display 🧪 partial badge so visitors see the honest state.",
                qa_report.get("verdict"), residual_dead,
            )

        # SECURITY GATE — REMOVED in Project Evolution per user directive.
        # Trade-off: less pre-publish review, more domain freedom, fewer false-
        # positive blocks. The architect prompt still mandates TOS compliance;
        # malicious patterns are guarded at the prompt level instead of a gate.

        # 7. PUBLISH (project_type aware: Pages enabled only for web types)
        log.info("════════ STAGE 7: PUBLISH ════════")
        repo_url, pages_url, owner = publish(plan, WORKSPACE, gh_token)
        log.info("Published: %s", repo_url)
        if pages_url:
            log.info("Pages:     %s", pages_url)
            verifier.verify_pages_live(pages_url, timeout=180)

        # 8. MEMORY + DASHBOARD
        log.info("════════ STAGE 8: MEMORY + DASHBOARD ════════")
        append_record(memory, plan, files, repo_url, pages_url, cycles_used,
                      final_verify, impl_meta, ceo_directives,
                      qa_report=qa_findings_to_record)
        dashboard.render_dashboard(memory, owner=owner)

        log.info("All stages complete.")
        return 0

    except pipeline.PipelineError as e:
        log.error("Pipeline error: %s", e)
        # Log to failed_builds so the CEO learns and recovery mode eventually activates.
        # Without this, conference failures are invisible — CEO keeps demanding the same
        # failing type indefinitely, and in_recovery never triggers.
        try:
            err_str = str(e)
            # Extract demanded type from CEO directives if available
            demanded_type = "unknown"
            for directive in (ceo_directives or []):
                for pt in pipeline.PROJECT_TYPES:
                    if pt in directive.lower():
                        demanded_type = pt
                        break
            # Also try to detect from error message itself
            for pt in pipeline.PROJECT_TYPES:
                if pt in err_str:
                    demanded_type = pt
                    break
            record_failure(
                memory,
                plan=None,
                stage="architect_conference",
                reason=f"Conference failed: {err_str[:300]}",
            )
            # Patch the project_type into the last record so type-ban logic works
            if memory.get("failed_builds"):
                memory["failed_builds"][-1]["project_type"] = demanded_type
                save_memory(memory)
            log.info("Logged conference failure (type=%s) to failed_builds.", demanded_type)
        except Exception as log_err:
            log.warning("Could not log conference failure: %s", log_err)
        # NON-HALTING: the architect could not produce a valid plan this run (often because
        # CEO directives demanded a maxed/banned type). This is recorded so recovery mode and
        # expansion mode can kick in on the next run. Exit 0 so the build is never marked
        # failed when it comes to the CEO review — the next scheduled run will try again.
        log.info("Conference failure recorded. Exiting 0 (non-halting mode).")
        return 0
    except Exception:
        # Genuine, unexpected crash (not a normal refusal). Keep this visible as a real
        # failure so actual bugs surface — this is NOT a CEO-review halt.
        log.error("Unhandled error:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
