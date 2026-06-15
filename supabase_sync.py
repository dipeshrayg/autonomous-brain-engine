"""
supabase_sync.py — best-effort mirror of engine state into Supabase (Postgres).

The engine's durable state is still memory_log.json (committed to git). This
module ADDITIONALLY pushes each shipped project, refused build, executive
review, and (optionally) log line into Supabase so the live dashboard and the
board demo read from a real, RLS-secured database.

Design rule: this module NEVER raises and NEVER fails a build. If SUPABASE_URL
/ SUPABASE_SERVICE_ROLE_KEY are unset, or Supabase is unreachable, every call
logs a warning and returns False. The pipeline proceeds regardless.

Writes use the SERVICE_ROLE key (bypasses RLS). The key comes from env, set as
a GitHub Actions secret — never committed, never sent to the browser.
"""

from __future__ import annotations

import json
import logging
import os

import requests

log = logging.getLogger("brain.supabase")

_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
_TIMEOUT = 15

_PROJECT_COLS = {
    "name", "date", "completed_at", "project_type", "language", "complexity_score",
    "pattern", "domain", "description", "long_description", "advancement_axis",
    "visual_identity", "safety_notes", "repo_url", "pages_url", "tech_stack",
    "concepts_demonstrated", "novel_concepts", "file_count", "loc",
    "quality_cycles_used", "qa_verdict", "qa_review", "final_verify_metrics",
    "model_attribution", "ceo_directives_followed",
}
_FAIL_COLS = {
    "plan_name", "project_type", "plan_language", "plan_complexity", "plan_pattern",
    "plan_domain", "plan_files_count", "refusal_stage", "refusal_reason",
    "qa_verdict", "qa_dead_controls", "qa_missing_features", "final_interaction",
    "final_interactive_count",
}
_REVIEW_COLS = {"verdict", "summary", "concerns", "directives", "praise", "model",
                "reviewed_project_count"}


def enabled() -> bool:
    return bool(_URL and _KEY)


def _headers(extra: dict | None = None) -> dict:
    h = {"apikey": _KEY, "Authorization": f"Bearer {_KEY}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _post(table: str, row: dict, on_conflict: str | None = None) -> bool:
    if not enabled():
        log.info("Supabase not configured; skipping %s sync.", table)
        return False
    url = f"{_URL}/rest/v1/{table}"
    if on_conflict:
        url += f"?on_conflict={on_conflict}"
    prefer = "return=minimal"
    if on_conflict:
        prefer += ",resolution=merge-duplicates"
    try:
        r = requests.post(url, headers=_headers({"Prefer": prefer}),
                          data=json.dumps([row]), timeout=_TIMEOUT)
        if r.status_code >= 300:
            log.warning("Supabase %s sync failed [%s]: %s", table, r.status_code, r.text[:200])
            return False
        log.info("Supabase: synced 1 row -> %s", table)
        return True
    except Exception as e:  # noqa: BLE001 — must never propagate
        log.warning("Supabase %s sync error: %s", table, e)
        return False


def _slug(rec: dict) -> str:
    repo = rec.get("repo_url") or ""
    if "/" in repo:
        tail = repo.rstrip("/").split("/")[-1]
        if tail:
            return tail
    return f"{rec.get('date', '')}-{rec.get('name', '')}".strip("-")


def sync_project(record: dict) -> bool:
    """Upsert a shipped-project record (idempotent on slug)."""
    row = {k: v for k, v in record.items() if k in _PROJECT_COLS}
    row["slug"] = _slug(record)
    row["project_type"] = row.get("project_type") or "unknown"
    if row.get("complexity_score") is None:
        row["complexity_score"] = 0
    for col in ("tech_stack", "concepts_demonstrated", "novel_concepts",
                "ceo_directives_followed"):
        if not row.get(col):
            row[col] = []
    return _post("projects", row, on_conflict="slug")


def sync_failed_build(record: dict) -> bool:
    """Insert a refused-build record."""
    row = {k: v for k, v in record.items() if k in _FAIL_COLS}
    att = record.get("attempted_at") or record.get("date")
    if att and len(str(att)) == 10:
        att = f"{att}T00:00:00Z"
    row["attempted_at"] = att
    for col in ("qa_dead_controls", "qa_missing_features"):
        if not row.get(col):
            row[col] = []
    return _post("failed_builds", row)


def sync_review(table: str, record: dict) -> bool:
    """Insert a CEO/CSO review. table is 'ceo_reviews' or 'cso_reviews'."""
    row = {k: v for k, v in record.items() if k in _REVIEW_COLS}
    row.setdefault("verdict", "acceptable")
    row["issued_at"] = record.get("issued_at")
    return _post(table, row)


def sync_system_state(memory: dict) -> bool:
    """Patch the singleton system_state row (expansion_mode flags)."""
    if not enabled():
        return False
    try:
        r = requests.patch(
            f"{_URL}/rest/v1/system_state?id=eq.1",
            headers=_headers({"Prefer": "return=minimal"}),
            data=json.dumps({
                "expansion_mode": bool(memory.get("expansion_mode", False)),
                "expansion_mode_since": memory.get("expansion_mode_since"),
            }),
            timeout=_TIMEOUT,
        )
        return r.status_code < 300
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase system_state sync error: %s", e)
        return False


def log_event(level: str, stage: str, message: str,
              project_slug: str | None = None, run_id: str | None = None,
              metadata: dict | None = None) -> bool:
    """Append a build-time log line to build_logs (auth-only read)."""
    return _post("build_logs", {
        "level": level,
        "stage": stage,
        "message": message[:2000],
        "project_slug": project_slug,
        "run_id": run_id or os.environ.get("GITHUB_RUN_ID"),
        "metadata": metadata or {},
    })
