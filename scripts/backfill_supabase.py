"""
backfill_supabase.py — one-time migration of memory_log.json into Supabase.

Reads the existing flat memory_log.json and loads it into the Postgres tables
defined in supabase/migrations/0001_initial_schema.sql, using the Supabase REST
(PostgREST) API with the SERVICE_ROLE key (which bypasses RLS).

Idempotent:
  * projects + taxonomy are UPSERTED on their unique keys (safe to re-run).
  * append-only tables (failed_builds, ceo_reviews, cso_reviews) are only loaded
    when currently empty, to avoid duplicates. Pass --reset to truncate+reload.

Usage:
  export SUPABASE_URL="https://<ref>.supabase.co"
  export SUPABASE_SERVICE_ROLE_KEY="<service_role key>"
  python scripts/backfill_supabase.py [--reset]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

MEMORY = Path("memory_log.json")
URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
RESET = "--reset" in sys.argv

if not URL or not KEY:
    print("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars.")
    sys.exit(2)

BASE = f"{URL}/rest/v1"
H = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
}


def _slug(p: dict) -> str:
    """Repo is named <date>-<name>; derive the slug the same way."""
    repo = p.get("repo_url") or ""
    if "/" in repo:
        tail = repo.rstrip("/").split("/")[-1]
        if tail:
            return tail
    return f"{p.get('date','')}-{p.get('name','')}".strip("-")


def _count(table: str) -> int:
    r = requests.get(f"{BASE}/{table}?select=id", headers={**H, "Prefer": "count=exact",
                     "Range": "0-0"})
    rng = r.headers.get("content-range", "*/0")
    try:
        return int(rng.split("/")[-1])
    except ValueError:
        return 0


def _truncate(table: str) -> None:
    # PostgREST has no TRUNCATE; delete all rows (id not null is always true).
    requests.delete(f"{BASE}/{table}?id=not.is.null", headers=H)


def _upsert(table: str, rows: list[dict], on_conflict: str) -> None:
    if not rows:
        return
    r = requests.post(
        f"{BASE}/{table}?on_conflict={on_conflict}",
        headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"},
        data=json.dumps(rows),
    )
    if r.status_code >= 300:
        print(f"  ! {table} upsert failed [{r.status_code}]: {r.text[:300]}")
    else:
        print(f"  OK upserted {len(rows)} -> {table}")


def _insert(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    r = requests.post(
        f"{BASE}/{table}",
        headers={**H, "Prefer": "return=minimal"},
        data=json.dumps(rows),
    )
    if r.status_code >= 300:
        print(f"  ! {table} insert failed [{r.status_code}]: {r.text[:300]}")
    else:
        print(f"  OK inserted {len(rows)} -> {table}")


def _load_if_empty(table: str, rows: list[dict]) -> None:
    if RESET:
        _truncate(table)
    elif _count(table) > 0:
        print(f"  - {table} already has rows; skipping (use --reset to reload).")
        return
    _insert(table, rows)


def main() -> int:
    mem = json.loads(MEMORY.read_text(encoding="utf-8"))
    print(f"Loaded {MEMORY} — {len(mem.get('projects', []))} projects, "
          f"{len(mem.get('failed_builds', []))} failed, "
          f"{len(mem.get('ceo_reviews', []))} ceo, {len(mem.get('cso_reviews', []))} cso.")

    # ---- projects (upsert on slug) ----
    PROJECT_COLS = {
        "name", "date", "completed_at", "project_type", "language", "complexity_score",
        "pattern", "domain", "description", "long_description", "advancement_axis",
        "visual_identity", "safety_notes", "repo_url", "pages_url", "tech_stack",
        "concepts_demonstrated", "novel_concepts", "file_count", "loc",
        "quality_cycles_used", "qa_verdict", "qa_review", "final_verify_metrics",
        "model_attribution", "ceo_directives_followed",
    }
    projects = []
    for p in mem.get("projects", []):
        row = {k: v for k, v in p.items() if k in PROJECT_COLS}
        row["slug"] = _slug(p)
        if not row.get("completed_at"):
            row["completed_at"] = f"{p.get('date','2026-01-01')}T00:00:00Z"
        if not row.get("date"):
            row["date"] = (row["completed_at"] or "2026-01-01")[:10]
        projects.append(row)
    print("projects:")
    _upsert("projects", projects, on_conflict="slug")

    # ---- failed_builds (append-only) ----
    FAIL_COLS = {
        "plan_name", "project_type", "plan_language", "plan_complexity", "plan_pattern",
        "plan_domain", "plan_files_count", "refusal_stage", "refusal_reason",
        "qa_verdict", "qa_dead_controls", "qa_missing_features", "final_interaction",
        "final_interactive_count",
    }
    fails = []
    for f in mem.get("failed_builds", []):
        row = {k: v for k, v in f.items() if k in FAIL_COLS}
        row["attempted_at"] = f.get("attempted_at") or f"{f.get('date','2026-01-01')}T00:00:00Z"
        fails.append(row)
    print("failed_builds:")
    _load_if_empty("failed_builds", fails)

    # ---- ceo_reviews / cso_reviews (append-only) ----
    REVIEW_COLS = {"verdict", "summary", "concerns", "directives", "praise", "model",
                   "reviewed_project_count"}
    for key, table in (("ceo_reviews", "ceo_reviews"), ("cso_reviews", "cso_reviews")):
        rows = []
        for rv in mem.get(key, []):
            row = {k: v for k, v in rv.items() if k in REVIEW_COLS}
            row["issued_at"] = rv.get("issued_at") or "2026-01-01T00:00:00Z"
            row.setdefault("verdict", "acceptable")
            rows.append(row)
        print(f"{table}:")
        _load_if_empty(table, rows)

    # ---- taxonomy (upsert on kind,value) ----
    taxo = []
    for value in mem.get("concepts_explored", []):
        taxo.append({"kind": "concept", "value": value})
    for value in mem.get("patterns_used", []):
        taxo.append({"kind": "pattern", "value": value})
    for value in mem.get("domains_used", []):
        taxo.append({"kind": "domain", "value": value})
    print("taxonomy:")
    _upsert("taxonomy", taxo, on_conflict="kind,value")

    # ---- system_state (singleton) ----
    print("system_state:")
    r = requests.patch(
        f"{BASE}/system_state?id=eq.1",
        headers={**H, "Prefer": "return=minimal"},
        data=json.dumps({
            "expansion_mode": bool(mem.get("expansion_mode", False)),
            "expansion_mode_since": mem.get("expansion_mode_since"),
        }),
    )
    print("  OK system_state updated" if r.status_code < 300
          else f"  ! system_state failed [{r.status_code}]: {r.text[:200]}")

    print("\nBackfill complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
