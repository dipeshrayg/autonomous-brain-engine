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
import security_officer

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
                  security_report: dict | None = None) -> None:
    now = datetime.now(timezone.utc)
    record = {
        "date": now.strftime("%Y-%m-%d"),
        "completed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at_unix": int(now.timestamp()),
        "name": plan["name"],
        "repo_url": repo_url,
        "pages_url": pages_url,
        "language": plan["language"],
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
        "security_review": (
            {
                "verdict": security_report.get("verdict"),
                "summary": security_report.get("summary"),
                "model": security_report.get("__model__"),
                "findings_count": len(security_report.get("findings") or []),
                "findings": security_report.get("findings") or [],
                "directives_for_future": security_report.get("directives_for_future") or [],
            }
            if security_report else None
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
    """Run browser verify for web projects; return structured result."""
    if not plan.get("is_web_project"):
        # Fallback for non-web (rare under new prompt) - simple sanity check.
        return {"errors": [], "issues": [], "metrics": {"non_web": True}, "screenshot": None}
    try:
        return verifier.verify_web(target, timeout=30)
    except Exception as e:
        log.exception("Browser verify crashed.")
        return {
            "errors": [f"verifier exception: {e}"],
            "issues": [f"Browser verifier crashed: {e}. Check that index.html parses."],
            "metrics": {},
            "screenshot": None,
        }


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

    pages_url = ""
    if plan.get("is_web_project"):
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

    client = OpenAI(base_url=GH_MODELS_BASE_URL, api_key=models_token)

    try:
        # CEO directives — top-of-house guidance for the architect conference.
        ceo_directives = executive.latest_directives(memory)
        if ceo_directives:
            log.info("CEO has issued %d active directive(s) the architect must obey.",
                     len(ceo_directives))
            for d in ceo_directives:
                log.info("  CEO: %s", d)

        # CSO directives — security mandates from the most recent audit.
        cso_directives = security_officer.latest_directives(memory)
        if cso_directives:
            log.info("CSO has issued %d active security directive(s).", len(cso_directives))
            for d in cso_directives:
                log.info("  CSO: %s", d)

        # Merge: CEO + CSO. Both must be obeyed. Architect sees both.
        all_directives = list(ceo_directives) + [
            f"[security] {d}" for d in cso_directives
        ]

        # 1. PLAN — multi-model architect conference
        log.info("════════ STAGE 1: ARCHITECT CONFERENCE ════════")
        plan = pipeline.stage_plan(client, memory, ceo_directives=all_directives)

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
            issues = (final_verify.get("errors") or []) + (final_verify.get("issues") or [])
            updates = pipeline.stage_fix(client, plan, files, issues)
            if updates:
                files = merge_updates(files, updates)
                materialize(files, WORKSPACE)
                final_verify = verify_project(plan, WORKSPACE)

        # Hard quality gate: refuse to publish a clearly broken project.
        blocking_issues = final_verify.get("errors", []) + [
            i for i in final_verify.get("issues", [])
            if "blank" in i.lower() or "empty" in i.lower() or "zero" in i.lower()
        ]
        if blocking_issues:
            log.error("Blocking issues remain after final verify - refusing to publish.")
            for i in blocking_issues:
                log.error("  - %s", i)
            return 1

        # 6.5 SECURITY REVIEW (CSO role: per-project pre-publish gate).
        # If critical/high findings, send to the Security Fixer (gpt-4o) for up
        # to 3 remediation rounds, re-reviewing after each. Refuse to publish
        # only if all rounds fail to clear the blocking findings.
        log.info("════════ STAGE 6.5: SECURITY REVIEW (Security Officer) ════════")
        sec_report = pipeline.stage_security_review(client, plan, files, final_verify)
        sec_findings_to_record = sec_report

        MAX_SEC_FIX_ROUNDS = 3
        round_num = 0
        while sec_report.get("verdict") == "publish_blocked" and round_num < MAX_SEC_FIX_ROUNDS:
            round_num += 1
            blocking_security = [
                f for f in (sec_report.get("findings") or [])
                if isinstance(f, dict) and f.get("severity") in ("critical", "high")
            ]
            log.warning(
                "Security round %d/%d: %d blocking finding(s) — calling security_fixer (gpt-4o).",
                round_num, MAX_SEC_FIX_ROUNDS, len(blocking_security),
            )
            sec_issues = [
                f"[{f.get('severity')}] [{f.get('category')}] {f.get('issue')} "
                f"-- suggestion: {f.get('suggestion')}"
                for f in blocking_security
            ]
            updates = pipeline.stage_security_fix(client, plan, files, sec_issues)
            if not updates:
                log.warning("Security fixer produced no updates; aborting remediation loop.")
                break
            files = merge_updates(files, updates)
            materialize(files, WORKSPACE)
            final_verify = verify_project(plan, WORKSPACE)
            sec_report = pipeline.stage_security_review(client, plan, files, final_verify)
            sec_findings_to_record = sec_report

        if sec_report.get("verdict") == "publish_blocked":
            log.error("Security gate STILL blocking after %d round(s) — refusing to publish.",
                      round_num)
            still_blocking = [
                f for f in (sec_report.get("findings") or [])
                if isinstance(f, dict) and f.get("severity") in ("critical", "high")
            ]
            for f in still_blocking:
                log.error("  [%s] [%s] %s",
                          f.get("severity", "?").upper(),
                          f.get("category", "?"),
                          f.get("issue", "")[:200])
            return 1

        # 7. PUBLISH
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
                      security_report=sec_findings_to_record)
        dashboard.render_dashboard(memory, owner=owner)

        log.info("All stages complete.")
        return 0

    except pipeline.PipelineError as e:
        log.error("Pipeline error: %s", e)
        return 1
    except Exception:
        log.error("Unhandled error:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
