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

# ─────────────────────── Configuration ──────────────────────────────────

GH_MODELS_BASE_URL = "https://models.inference.ai.azure.com"
MODEL = "gpt-4o"

MAX_QUALITY_CYCLES = 4       # critique+fix iterations
TEST_TIMEOUT_SECONDS = 300

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


def append_record(memory: dict[str, Any], plan: dict, files: dict[str, str],
                  repo_url: str, pages_url: str, cycles: int,
                  verify_result: dict) -> None:
    record = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "name": plan["name"],
        "repo_url": repo_url,
        "pages_url": pages_url,
        "language": plan["language"],
        "tech_stack": plan.get("tech_stack", []),
        "complexity_score": int(plan.get("complexity_score", 0)),
        "concepts_demonstrated": plan.get("concepts_demonstrated", []),
        "novel_concepts": plan.get("novel_concepts", []),
        "advancement_axis": plan.get("advancement_axis", ""),
        "safety_notes": plan.get("safety_notes", ""),
        "file_count": len(files),
        "loc": sum(c.count("\n") + 1 for c in files.values()),
        "quality_cycles_used": cycles,
        "final_verify_metrics": verify_result.get("metrics", {}),
    }
    memory.setdefault("projects", []).append(record)
    memory.setdefault("complexity_trajectory", []).append(record["complexity_score"])
    explored = memory.setdefault("concepts_explored", [])
    for c in (plan.get("concepts_demonstrated") or []):
        if c not in explored:
            explored.append(c)
    save_memory(memory)
    log.info("Memory updated: project #%d.", len(memory["projects"]))


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
    repo_name = date_prefixed_name(plan["name"])
    log.info("Creating GitHub repo %s/%s", user.login, repo_name)
    try:
        repo = user.create_repo(
            name=repo_name,
            description=plan["description"][:350],
            private=False,
            has_issues=True,
            has_wiki=False,
            auto_init=False,
        )
    except GithubException as e:
        raise RuntimeError(f"create_repo failed: {e}") from e

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

def implement_all(client: OpenAI, plan: dict) -> dict[str, str]:
    """Generate every file in the plan, in order."""
    files: dict[str, str] = {}
    for fs in plan["files"]:
        log.info("IMPLEMENT %s", fs["path"])
        path, content = pipeline.stage_implement(client, MODEL, plan, fs, files)
        files[path] = content
    log.info("Implemented %d file(s) totalling %d chars.",
             len(files), sum(len(c) for c in files.values()))
    return files


def quality_loop(client: OpenAI, plan: dict, files: dict[str, str],
                 target: Path) -> tuple[dict[str, str], int, dict]:
    """Verify -> critique -> fix; loop until clean or budget exhausted."""
    materialize(files, target)
    verify = verify_project(plan, target)
    cycles = 0
    last_verify = verify

    for cycle in range(1, MAX_QUALITY_CYCLES + 1):
        # Combine mechanical + semantic feedback.
        log.info("CRITIQUE cycle %d (browser issues=%d, errors=%d)",
                 cycle, len(verify.get("issues", [])), len(verify.get("errors", [])))
        critique = pipeline.stage_critique(client, MODEL, plan, files, verify)
        verdict = critique.get("verdict", "fix")
        must_fix = critique.get("must_fix") or []
        log.info("Critique verdict=%s, must_fix=%d, summary=%s",
                 verdict, len(must_fix), critique.get("summary", "")[:200])

        all_issues: list[str] = []
        all_issues.extend(verify.get("errors", []))
        all_issues.extend(verify.get("issues", []))
        for item in must_fix:
            if isinstance(item, dict):
                f = item.get("file", "")
                msg = f"{item.get('issue', '')}  -- suggestion: {item.get('suggestion', '')}"
                all_issues.append(f"[{f}] {msg}")

        if verdict == "ship" and not all_issues:
            log.info("Critique says SHIP and zero issues - quality loop done.")
            return files, cycles, verify

        if not all_issues:
            log.info("Critique non-ship but produced no must_fix items; treating as ship.")
            return files, cycles, verify

        log.info("FIX cycle %d - %d issue(s) to address.", cycle, len(all_issues))
        updates = pipeline.stage_fix(client, MODEL, plan, files, all_issues)
        if not updates:
            log.warning("Fix returned zero updates; giving up on this cycle.")
            break

        files = merge_updates(files, updates)
        materialize(files, target)
        verify = verify_project(plan, target)
        last_verify = verify
        cycles = cycle

        # Early exit: if browser verify is now clean AND critique was non-blocking.
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

    # Idempotency: scheduled runs skip if today's already done. Manual runs always run.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "schedule" and any(p.get("date") == today for p in memory.get("projects", [])):
        log.info("Today (%s) already has a project; scheduled run skipping.", today)
        return 0

    client = OpenAI(base_url=GH_MODELS_BASE_URL, api_key=models_token)

    try:
        # 1. PLAN
        log.info("════════ STAGE 1: PLAN ════════")
        plan = pipeline.stage_plan(client, MODEL, memory)

        # 2. IMPLEMENT
        log.info("════════ STAGE 2: IMPLEMENT ════════")
        files = implement_all(client, plan)

        # 3+4. QUALITY LOOP (verify ↔ critique ↔ fix)
        log.info("════════ STAGE 3+4: QUALITY LOOP ════════")
        files, cycles_used, _ = quality_loop(client, plan, files, WORKSPACE)

        # 5. POLISH
        log.info("════════ STAGE 5: POLISH ════════")
        polish_updates = pipeline.stage_polish(client, MODEL, plan, files)
        if polish_updates:
            files = merge_updates(files, polish_updates)
            materialize(files, WORKSPACE)

        # 6. FINAL VERIFY
        log.info("════════ STAGE 6: FINAL VERIFY ════════")
        final_verify = verify_project(plan, WORKSPACE)
        if final_verify.get("errors") or final_verify.get("issues"):
            log.warning("Polish introduced issues; running one fix pass.")
            issues = (final_verify.get("errors") or []) + (final_verify.get("issues") or [])
            updates = pipeline.stage_fix(client, MODEL, plan, files, issues)
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

        # 7. PUBLISH
        log.info("════════ STAGE 7: PUBLISH ════════")
        repo_url, pages_url, owner = publish(plan, WORKSPACE, gh_token)
        log.info("Published: %s", repo_url)
        if pages_url:
            log.info("Pages:     %s", pages_url)
            verifier.verify_pages_live(pages_url, timeout=180)

        # 8. MEMORY + DASHBOARD
        log.info("════════ STAGE 8: MEMORY + DASHBOARD ════════")
        append_record(memory, plan, files, repo_url, pages_url, cycles_used, final_verify)
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
