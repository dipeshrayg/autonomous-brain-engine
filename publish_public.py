"""
publish_public.py - Sanitize memory and push the public dashboard.

Called at the end of every engine workflow that mutates memory_log.json
(daily_build, ceo_review, security_review). Reads the engine's memory_log,
strips engine-internal fields, regenerates README.md + index.html, then
clones the public dashboard repo, copies the sanitized files in, and pushes
if anything changed.

What gets stripped before public exposure:
  - Per-project: model_attribution (which LLM did what), ceo_directives_followed
    (the verbatim CEO/CSO directives), detailed verifier metrics, full security-
    review findings (only verdict + count survives).
  - CEO reviews: keep verdict + summary + issued_at; strip concerns + directives.
  - CSO audits: same as CEO reviews.
The ledger remains useful for the public showcase; the engine's strategic
output stays private.

Requires GH_PAT in env. Returns shell exit code; does NOT raise on push
failures (logs and exits 0) so a transient sync hiccup doesn't fail the
caller workflow.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("brain.publish_public")

PUBLIC_REPO = "dipeshrayg/autonomous-brain"
PUBLIC_BRANCH = "main"
ENGINE_OWNER = "dipeshrayg"


def sanitize_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy memory and strip engine-internal fields."""
    out = json.loads(json.dumps(memory))

    for p in out.get("projects", []) or []:
        # Internal model attribution stays private
        p.pop("model_attribution", None)
        p.pop("ceo_directives_followed", None)
        # Trim verifier metrics to a public summary only
        if "final_verify_metrics" in p and p["final_verify_metrics"]:
            metrics = p["final_verify_metrics"]
            p["final_verify_metrics"] = {
                "interactiveCount": metrics.get("interactiveCount"),
                "canvasCount": metrics.get("canvasCount"),
                "title": metrics.get("title"),
            }
        # Trim security review to verdict + count
        sr = p.get("security_review")
        if sr:
            p["security_review"] = {
                "verdict": sr.get("verdict"),
                "findings_count": sr.get("findings_count", 0),
            }

    # CEO + CSO: verdict + summary only (concerns + directives are internal coaching)
    out["ceo_reviews"] = [
        {
            "issued_at": r.get("issued_at"),
            "verdict": r.get("verdict"),
            "summary": r.get("summary"),
            "model": r.get("model"),
        }
        for r in (out.get("ceo_reviews") or [])
    ]
    out["security_audits"] = [
        {
            "issued_at": r.get("issued_at"),
            "verdict": r.get("verdict"),
            "summary": r.get("summary"),
            "model": r.get("model"),
        }
        for r in (out.get("security_audits") or [])
    ]
    return out


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> tuple[int, str]:
    # Avoid leaking the GH_PAT in the visible command line.
    safe_cmd = [
        ("https://x-access-token:***@github.com/" if c.startswith("https://x-access-token:") else c)
        for c in cmd
    ]
    log.info("$ %s   (cwd=%s)", " ".join(safe_cmd), cwd)
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = (proc.stdout + "\n" + proc.stderr).strip()
    if proc.returncode != 0:
        # Surface the failure regardless of `check` so we can debug push errors.
        log.error("command exit=%d\n%s", proc.returncode, out[-1500:])
    return proc.returncode, out


def main() -> int:
    gh_pat = os.environ.get("GH_PAT")
    if not gh_pat:
        log.error("GH_PAT env var required for cross-repo push.")
        return 2

    memory_path = Path("memory_log.json")
    if not memory_path.exists():
        log.warning("No memory_log.json in cwd; nothing to publish.")
        return 0
    memory = json.loads(memory_path.read_text(encoding="utf-8"))

    sanitized = sanitize_memory(memory)
    log.info(
        "Sanitized memory: %d projects, %d ceo_reviews, %d security_audits.",
        len(sanitized.get("projects", [])),
        len(sanitized.get("ceo_reviews", [])),
        len(sanitized.get("security_audits", [])),
    )

    with tempfile.TemporaryDirectory(prefix="public-sync-") as tmp:
        tmp_path = Path(tmp) / "public"
        remote = f"https://x-access-token:{gh_pat}@github.com/{PUBLIC_REPO}.git"

        rc, out = _run(["git", "clone", "--depth", "5", "--branch", PUBLIC_BRANCH,
                        remote, str(tmp_path)], check=False)
        if rc != 0:
            log.error("Clone of public repo failed; aborting sync (will retry next run).")
            return 0  # don't fail the caller workflow

        # Write sanitized memory
        with (tmp_path / "memory_log.json").open("w", encoding="utf-8") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)
            f.write("\n")

        # Render README + index.html into the public clone
        sys.path.insert(0, os.getcwd())
        import dashboard  # noqa: E402

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            dashboard.render_dashboard(sanitized, owner=ENGINE_OWNER, repo="autonomous-brain")
        finally:
            os.chdir(original_cwd)

        # Commit + push if changed
        _run(["git", "config", "user.name", "engine-bot[autonomous-brain]"], cwd=tmp_path)
        _run(["git", "config", "user.email",
              "engine-bot@users.noreply.github.com"], cwd=tmp_path)
        _run(["git", "add", "-A"], cwd=tmp_path)
        rc, _ = _run(["git", "diff", "--staged", "--quiet"], cwd=tmp_path, check=False)
        if rc == 0:
            log.info("✓ Public dashboard already up to date.")
            return 0

        msg = f"sync: dashboard from engine @ {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}"
        rc, _ = _run(["git", "commit", "-m", msg], cwd=tmp_path, check=False)
        if rc != 0:
            log.warning("Commit failed; aborting sync.")
            return 0
        rc, _ = _run(["git", "push", "origin", PUBLIC_BRANCH],
                     cwd=tmp_path, check=False)
        if rc != 0:
            log.warning("Push to public failed; will retry next run.")
            return 0

        log.info("✓ Synced public dashboard: %s", msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
