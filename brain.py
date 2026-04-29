#!/usr/bin/env python3
"""
brain.py - Master orchestrator for the daily autonomous build pipeline.

Uses GitHub Models (free tier) as the LLM backend. No paid API keys needed.

Each run:
  1. Loads memory_log.json (history of past projects).
  2. Asks the model to design a new project that advances on past complexity.
  3. Validates the spec, materializes files into ./workspace.
  4. Runs the project's setup + test commands; on failure, feeds the error
     back to the model and retries (capped at MAX_RETRIES).
  5. Creates a fresh public GitHub repo, pushes the code.
  6. Enables GitHub Pages if the project is web-compatible.
  7. Appends the run to memory_log.json (committed back by the workflow).
"""

from __future__ import annotations

import json
import logging
import os
import re
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

# ---------- Configuration ----------------------------------------------

# GitHub Models - OpenAI-compatible, authenticated via GITHUB_TOKEN.
# Swap MODEL to "gpt-4o-mini" for higher daily rate limits if you hit caps,
# or to "Meta-Llama-3.1-405B-Instruct" / "Mistral-Large-2411" for variety.
GH_MODELS_BASE_URL = "https://models.inference.ai.azure.com"
MODEL = "gpt-4o"

MAX_RETRIES = 5
MAX_OUTPUT_TOKENS = 4000           # free-tier ceiling for most models
TEST_TIMEOUT_SECONDS = 300
HISTORY_WINDOW = 14

MEMORY_LOG_PATH = Path("memory_log.json")
WORKSPACE = Path("workspace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("brain")

# ---------- Prompt -----------------------------------------------------

SYSTEM_PROMPT = """You are the Chief Architect of an autonomous, daily software-creation pipeline. Each day you design and write a brand new, runnable, educational software project that advances on the complexity of previous days.

ABSOLUTE CONSTRAINTS - non-negotiable. Violation aborts the run:
1. Comply strictly with GitHub's Terms of Service and Acceptable Use Policy.
2. Do NOT generate active malware, ransomware, credential stealers, botnets, reverse shells, persistence implants, sandbox-escape exploits, network worms, or anything that operates against systems without explicit consent.
3. Security-themed projects must be EDUCATIONAL or DIAGNOSTIC only - simulations, explainers, or sandboxed demos that operate solely on the user's own data with consent. The README must explicitly state the educational nature and the safety boundary.
4. No mass spam, harassment, scraping of protected/auth-walled data, or detection-evasion tooling.
5. No exfiltration or unsolicited network calls. Calls to well-known public APIs are fine if disclosed in the README.

OUTPUT FORMAT - respond with a SINGLE JSON object. No prose. No markdown fences. Schema:
{
  "name": "kebab-case-repo-name (ascii, 3-60 chars)",
  "description": "one-line description (max 200 chars)",
  "long_description": "2-4 paragraph project description for the README body",
  "language": "primary language (Python | JavaScript | TypeScript | Go | Rust | C++ | Java | HTML | Bash | ...)",
  "tech_stack": ["specific libs/frameworks/tools"],
  "is_web_project": false,
  "complexity_score": 1-10,
  "concepts_demonstrated": ["non-trivial ideas this project demonstrates"],
  "safety_notes": "Plain-English explanation of any safety considerations and how the educational/diagnostic boundary is preserved. Required even for non-security projects ('N/A - pure utility' is fine).",
  "files": [
    {"path": "relative/path/from/repo/root.ext", "content": "full file contents"}
  ],
  "setup_commands": ["shell commands to run before tests, e.g. 'pip install -r requirements.txt'"],
  "test_command": "single shell command that exits 0 on success and non-zero on failure"
}

CODE RULES:
- All file paths are relative; no '..', no absolute paths, no symlinks.
- Always include a comprehensive README.md describing purpose, tech stack, how to run, and (when applicable) the safety/loophole disclosures.
- Pin dependency versions where reasonable.
- Code must run as-is on a fresh Ubuntu 22.04 GitHub Actions runner (Python, Node, Go, Rust, gcc/g++, Java, .NET are pre-installed).
- The full setup + test sequence must complete in under 5 minutes.

DEPLOYMENT REQUIREMENT — every project MUST be runnable from a single URL with zero installation:
- DEFAULT to building the project in HTML + CSS + JavaScript with `index.html` at the repo root. Use Canvas, SVG, WebGL for visualizations; Web Audio for sound; small CDN libraries (p5.js, three.js, tone.js, tensorflow.js, d3.js, chart.js, etc.) where they help.
- ALWAYS set is_web_project=true and include a working `index.html` at repo root that loads instantly when GitHub Pages serves it. The page must be self-contained (no build step) — use ES modules from CDN if you need them.
- Algorithmic projects (mazes, sorts, graphs, neural nets, simulations, fractals, cellular automata, physics, music, raycasting, compression, crypto demos, etc.) translate beautifully to Canvas + JS — choose this style by default.
- You may use a non-web language ONLY if you ALSO include a complete browser-runnable demo of the same idea in index.html. Treat the non-web code as supplementary reference, not the primary deliverable.
- Test commands for web projects can be lightweight: `node -e "require('fs').readFileSync('index.html')"` or a small `puppeteer`/HTML validator script. Make sure tests reflect that the index.html is well-formed.
- Vary the IDEAS, LIBRARIES, and DOMAINS across projects — the variety lives in what the project does, not what language it's written in.

SIZE CONSTRAINT - your response budget is tight (~4000 output tokens):
- Prefer 1-4 focused files over sprawling multi-file architectures.
- Keep total file contents under ~2500 words combined.
- Lean on existing libraries instead of reinventing primitives.
- A small, runnable, *novel* idea beats a large, fragile one.

EVOLUTION DIRECTIVE:
Today's project must be MORE ADVANCED than recent history along at least one explicit axis: algorithmic depth, mathematical sophistication, architectural pattern, novel domain, or systems-level concept. Vary languages and domains; do not stagnate. Avoid repeating concepts you've demonstrated unless you are extending them substantively.
"""

# ---------- Memory -----------------------------------------------------

def load_memory() -> dict[str, Any]:
    if not MEMORY_LOG_PATH.exists():
        return {"projects": [], "complexity_trajectory": [], "concepts_explored": []}
    with MEMORY_LOG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(memory: dict[str, Any]) -> None:
    with MEMORY_LOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)
        f.write("\n")


def summarize_memory(memory: dict[str, Any]) -> str:
    recent = memory.get("projects", [])[-HISTORY_WINDOW:]
    if not recent:
        return "No previous projects. This is day 1 - pick a non-trivial idea around complexity 3."
    lines = ["Recent project history (oldest -> newest):"]
    for p in recent:
        concepts = ", ".join(p.get("concepts_demonstrated", [])[:5])
        errs = p.get("errors_encountered_count", 0)
        lines.append(
            f"- {p.get('date')}  \"{p.get('name')}\"  "
            f"[{p.get('language')}, complexity {p.get('complexity_score')}]"
            f"  concepts: {concepts}"
            + (f"  retries: {errs}" if errs else "")
        )
    avg = sum(p.get("complexity_score", 0) for p in recent) / len(recent)
    lines.append("")
    lines.append(f"Average recent complexity: {avg:.1f}. Today must clearly exceed this.")
    explored = memory.get("concepts_explored", [])[-30:]
    if explored:
        lines.append(f"Already-explored concepts (avoid verbatim repeats): {', '.join(explored)}")
    return "\n".join(lines)

# ---------- GitHub Models call -----------------------------------------

def build_user_message(memory_summary: str, retry_context: str | None) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = [f"Today is {today}. Design today's project. Respond with a single JSON object matching the schema.", "", memory_summary]
    if retry_context:
        parts += ["", "---- PREVIOUS ATTEMPT FAILED ----", retry_context,
                  "Diagnose the root cause and return the FULL corrected JSON spec."]
    return "\n".join(parts)


def call_model(client: OpenAI, user_message: str) -> dict[str, Any]:
    log.info("Calling GitHub Models (%s, ~%d input chars)", MODEL, len(user_message))
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.9,
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content or ""
    if resp.usage:
        log.info("Tokens - prompt: %d  completion: %d  total: %d",
                 resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.total_tokens)
    return parse_json(text)


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Model did not return JSON. First 500 chars:\n{text[:500]}")
    return json.loads(text[start:end + 1])

# ---------- Spec validation & materialization --------------------------

REQUIRED = {
    "name", "description", "long_description", "language", "tech_stack",
    "is_web_project", "complexity_score", "concepts_demonstrated",
    "safety_notes", "files", "setup_commands", "test_command",
}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$")


def validate_spec(spec: dict[str, Any]) -> None:
    missing = REQUIRED - spec.keys()
    if missing:
        raise ValueError(f"Spec missing fields: {sorted(missing)}")
    if not NAME_RE.match(spec["name"]):
        raise ValueError(f"Invalid repo name: {spec['name']!r}")
    if not isinstance(spec["files"], list) or not spec["files"]:
        raise ValueError("Spec must include at least one file")
    has_readme = False
    for f in spec["files"]:
        path = f.get("path", "")
        if not path or Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError(f"Unsafe file path: {path!r}")
        if not isinstance(f.get("content"), str):
            raise ValueError(f"File {path!r} has non-string content")
        if Path(path).name.lower() == "readme.md":
            has_readme = True
    if not has_readme:
        raise ValueError("Spec must include a README.md")


def materialize(spec: dict[str, Any], target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for f in spec["files"]:
        dest = target / f["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f["content"], encoding="utf-8")
    log.info("Materialized %d files into %s", len(spec["files"]), target)

# ---------- Test runner ------------------------------------------------

def run_command(cmd: str, cwd: Path, timeout: int) -> tuple[int, str]:
    log.info("$ %s   (cwd=%s)", cmd, cwd)
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(cwd),
            capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s\n{e.stdout or ''}\n{e.stderr or ''}"


def run_tests(spec: dict[str, Any], target: Path) -> tuple[bool, str]:
    for cmd in spec.get("setup_commands") or []:
        rc, out = run_command(cmd, target, TEST_TIMEOUT_SECONDS)
        if rc != 0:
            return False, f"Setup command failed: {cmd}\nExit {rc}\n{out[-4000:]}"
    cmd = spec.get("test_command")
    if not cmd:
        return True, "No test_command provided."
    rc, out = run_command(cmd, target, TEST_TIMEOUT_SECONDS)
    if rc != 0:
        return False, f"Test command failed: {cmd}\nExit {rc}\n{out[-4000:]}"
    return True, out[-2000:]

# ---------- GitHub publishing ------------------------------------------

def date_prefixed_name(name: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{today}-{name}"[:99]


def publish(spec: dict[str, Any], src: Path, gh_token: str) -> tuple[str, str]:
    g = Github(gh_token)
    user = g.get_user()
    repo_name = date_prefixed_name(spec["name"])
    log.info("Creating GitHub repo %s/%s", user.login, repo_name)
    try:
        repo = user.create_repo(
            name=repo_name,
            description=spec["description"][:350],
            private=False,
            has_issues=True,
            has_wiki=False,
            auto_init=False,
        )
    except GithubException as e:
        raise RuntimeError(f"create_repo failed: {e}") from e

    remote = f"https://x-access-token:{gh_token}@github.com/{user.login}/{repo_name}.git"
    git_steps = [
        "git init -b main",
        'git config user.name "autonomous-brain[bot]"',
        'git config user.email "autonomous-brain@users.noreply.github.com"',
        "git add .",
        f'git commit -m "Initial commit: {spec["name"]} (complexity {spec["complexity_score"]})"',
        f"git remote add origin {remote}",
        "git push -u origin main",
    ]
    for cmd in git_steps:
        rc, out = run_command(cmd, src, 120)
        if rc != 0:
            raise RuntimeError(f"git step failed `{cmd}`:\n{out}")

    pages_url = ""
    if spec.get("is_web_project"):
        pages_url = enable_pages(repo.full_name, repo.owner.login, repo.name, gh_token)
    return repo.html_url, pages_url


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

# ---------- Memory update ----------------------------------------------

def update_memory(memory: dict[str, Any], spec: dict[str, Any],
                  repo_url: str, pages_url: str, errors: list[str]) -> None:
    record = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "name": spec["name"],
        "repo_url": repo_url,
        "pages_url": pages_url,
        "language": spec["language"],
        "tech_stack": spec.get("tech_stack", []),
        "complexity_score": spec.get("complexity_score", 0),
        "concepts_demonstrated": spec.get("concepts_demonstrated", []),
        "safety_notes": spec.get("safety_notes", ""),
        "errors_encountered_count": len(errors),
    }
    memory.setdefault("projects", []).append(record)
    memory.setdefault("complexity_trajectory", []).append(spec.get("complexity_score", 0))
    explored = memory.setdefault("concepts_explored", [])
    for c in spec.get("concepts_demonstrated", []):
        if c not in explored:
            explored.append(c)
    save_memory(memory)
    log.info("Memory log updated.")

# ---------- Dashboard rendering ----------------------------------------

README_PATH = Path("README.md")
INDEX_PATH = Path("index.html")


def render_dashboard(memory: dict[str, Any], owner: str, repo: str = "autonomous-brain") -> None:
    """Regenerate README.md and index.html from the current memory log."""
    projects = list(reversed(memory.get("projects", [])))
    total = len(projects)
    avg = (sum(p.get("complexity_score", 0) for p in projects) / total) if total else 0
    languages = sorted({p.get("language", "?") for p in projects})
    latest = projects[0]["date"] if projects else "—"

    # ---- README.md ----
    rows = []
    for p in projects[:30]:
        concepts = ", ".join((p.get("concepts_demonstrated") or [])[:3])
        gh_path = (p.get("repo_url") or "").replace("https://github.com/", "")
        cs_url = f"https://codespaces.new/{gh_path}" if gh_path else ""
        run_links = []
        if p.get("pages_url"):
            run_links.append(f"[▶ run]({p['pages_url']})")
        if cs_url:
            run_links.append(f"[⚡ codespaces]({cs_url})")
        run_cell = " · ".join(run_links) if run_links else "—"
        rows.append(
            f"| {p.get('date')} | [{p.get('name')}]({p.get('repo_url')}) "
            f"| {p.get('language')} | {p.get('complexity_score')}/10 | {concepts} | {run_cell} |"
        )
    table = "\n".join(rows) if rows else "| — | _no projects yet_ | — | — | — | — |"

    readme = f"""# 🤖 Autonomous Brain

A self-improving AI software-engineering pipeline. Every day at 06:00 UTC, a
GitHub Action wakes up, asks an LLM (free GitHub Models) to design a brand-new
project that's more advanced than yesterday's, generates the code, tests it,
publishes it as a new repo, and remembers what it built.

📊 **Live dashboard:** https://{owner}.github.io/{repo}/
🔁 **Schedule:** daily 06:00 UTC · **Cost:** $0 · **Source:** [`brain.py`](brain.py)

## Stats

- **Total projects:** {total}
- **Average complexity:** {avg:.1f} / 10
- **Latest run:** {latest}
- **Languages explored:** {', '.join(languages) if languages else '—'}

## Latest creations

| Date | Project | Lang | ★ | Concepts | Run |
|------|---------|------|---|----------|-----|
{table}

---

*Generated automatically by `brain.py`. All projects are educational/diagnostic
and TOS-compliant. Last updated {latest}.*
"""
    README_PATH.write_text(readme, encoding="utf-8")
    log.info("README.md regenerated (%d projects).", total)

    # ---- index.html (Pages dashboard) ----
    INDEX_PATH.write_text(_DASHBOARD_HTML, encoding="utf-8")
    log.info("index.html regenerated.")


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Autonomous Brain — Daily Creations</title>
<style>
  *,*::before,*::after{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       max-width:1200px;margin:0 auto;padding:2rem 1rem;
       background:#0d1117;color:#c9d1d9;line-height:1.5}
  h1{color:#58a6ff;margin:0 0 .25rem;font-size:2rem}
  .sub{color:#8b949e;margin:0 0 2rem}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:1rem;padding:1.25rem;background:#161b22;border:1px solid #30363d;
         border-radius:8px;margin-bottom:2rem}
  .stat-num{font-size:2rem;font-weight:700;color:#58a6ff;line-height:1}
  .stat-label{font-size:.8rem;color:#8b949e;margin-top:.25rem;text-transform:uppercase;letter-spacing:.5px}
  .grid{display:grid;gap:1rem;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.25rem;
        transition:border-color .15s,transform .15s}
  .card:hover{border-color:#58a6ff;transform:translateY(-2px)}
  .card h3{margin:0 0 .5rem;font-size:1.05rem}
  .card h3 a{color:#58a6ff;text-decoration:none}
  .card h3 a:hover{text-decoration:underline}
  .meta{font-size:.85rem;color:#8b949e;margin-bottom:.75rem}
  .badge{display:inline-block;padding:2px 8px;border-radius:12px;background:#21262d;
         font-size:.75rem;margin-right:4px;color:#c9d1d9}
  .star{color:#f1c40f;font-weight:600}
  .concepts{font-size:.85rem;color:#c9d1d9}
  .actions{display:flex;gap:.5rem;margin-top:.9rem;flex-wrap:wrap}
  .btn{display:inline-block;padding:.4rem .75rem;border-radius:6px;font-size:.82rem;
       text-decoration:none;border:1px solid #30363d;color:#c9d1d9;background:#21262d;
       transition:border-color .15s,background .15s}
  .btn:hover{border-color:#58a6ff}
  .btn.primary{background:#238636;border-color:#2ea043;color:#fff;font-weight:600}
  .btn.primary:hover{background:#2ea043;border-color:#3fb950}
  .btn.ghost{background:transparent}
  footer{margin-top:3rem;padding-top:1.5rem;border-top:1px solid #30363d;
         color:#8b949e;font-size:.85rem;text-align:center}
  footer a{color:#58a6ff}
</style>
</head>
<body>
<h1>🤖 Autonomous Brain</h1>
<p class="sub">An AI that designs, codes, tests, and publishes a new software project every day. Runs free on GitHub Actions + GitHub Models.<br>
Click <b>▶ Run it</b> to play any project instantly in your browser, or <b>⚡ Codespaces</b> to open a free in-browser dev environment.</p>

<div class="stats">
  <div><div class="stat-num" id="count">—</div><div class="stat-label">Projects</div></div>
  <div><div class="stat-num" id="avg">—</div><div class="stat-label">Avg complexity</div></div>
  <div><div class="stat-num" id="langs">—</div><div class="stat-label">Languages</div></div>
  <div><div class="stat-num" id="latest">—</div><div class="stat-label">Latest</div></div>
</div>

<div id="grid" class="grid"></div>

<footer>
  Updates daily 06:00 UTC · <a href="memory_log.json">memory_log.json</a>
</footer>

<script>
fetch('memory_log.json?_=' + Date.now()).then(r => r.json()).then(m => {
  const projects = (m.projects || []).slice().reverse();
  document.getElementById('count').textContent = projects.length;
  if (projects.length) {
    const avg = projects.reduce((s,p)=>s+(p.complexity_score||0),0) / projects.length;
    document.getElementById('avg').textContent = avg.toFixed(1);
    document.getElementById('langs').textContent = new Set(projects.map(p=>p.language)).size;
    document.getElementById('latest').textContent = projects[0].date;
  }
  const grid = document.getElementById('grid');
  for (const p of projects) {
    const c = document.createElement('div');
    c.className = 'card';
    const concepts = (p.concepts_demonstrated || []).slice(0,4).join(' · ');
    const ghPath = (p.repo_url || '').replace('https://github.com/', '');
    const codespaces = ghPath ? `https://codespaces.new/${ghPath}` : '';
    c.innerHTML = `
      <h3><a href="${p.repo_url}" target="_blank" rel="noopener">${p.name}</a></h3>
      <div class="meta">${p.date} · <span class="badge">${p.language}</span> <span class="star">★ ${p.complexity_score}/10</span></div>
      <div class="concepts">${concepts}</div>
      <div class="actions">
        ${p.pages_url ? `<a class="btn primary" href="${p.pages_url}" target="_blank" rel="noopener">▶ Run it</a>` : ''}
        ${codespaces ? `<a class="btn" href="${codespaces}" target="_blank" rel="noopener">⚡ Codespaces</a>` : ''}
        <a class="btn ghost" href="${p.repo_url}" target="_blank" rel="noopener">&lt;/&gt; Source</a>
      </div>
    `;
    grid.appendChild(c);
  }
}).catch(e => {
  document.getElementById('grid').innerHTML = '<p style="color:#f85149">Failed to load memory log: ' + e.message + '</p>';
});
</script>
</body>
</html>
"""

# ---------- Main -------------------------------------------------------

def main() -> int:
    models_token = os.environ.get("GITHUB_TOKEN")  # for GitHub Models (free)
    gh_token = os.environ.get("GH_PAT")            # for cross-repo creation
    if not models_token or not gh_token:
        log.error("GITHUB_TOKEN and GH_PAT environment variables are required.")
        return 2

    memory = load_memory()

    # Idempotency: if today already has a project AND this is a scheduled run,
    # skip silently. The 18:17 UTC backup cron exists to catch missed primaries,
    # not to double up. Manual workflow_dispatch always runs.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    already_done = any(p.get("date") == today for p in memory.get("projects", []))
    if already_done and event == "schedule":
        log.info("Today (%s) already has a project; scheduled run skipping.", today)
        return 0

    client = OpenAI(base_url=GH_MODELS_BASE_URL, api_key=models_token)
    memory_summary = summarize_memory(memory)

    retry_context: str | None = None
    errors: list[str] = []
    spec: dict[str, Any] | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        log.info("======== Attempt %d / %d ========", attempt, MAX_RETRIES)
        try:
            user_msg = build_user_message(memory_summary, retry_context)
            spec = call_model(client, user_msg)
            validate_spec(spec)
            materialize(spec, WORKSPACE)
            ok, output = run_tests(spec, WORKSPACE)
            if ok:
                log.info("Build & tests passed on attempt %d.", attempt)
                break
            log.warning("Tests failed:\n%s", output)
            errors.append(output)
            retry_context = (
                f"Attempt {attempt} failed during testing.\n\n{output}\n\n"
                "Identify the root cause and return the corrected full JSON spec."
            )
        except Exception as e:
            tb = traceback.format_exc()
            log.warning("Attempt %d crashed: %s", attempt, e)
            errors.append(tb)
            retry_context = (
                f"Attempt {attempt} crashed before tests could complete:\n{tb}\n"
                "Likely causes: malformed JSON, missing required fields, or unsafe file paths. "
                "Return a corrected full JSON spec."
            )
            spec = None
    else:
        log.error("Exhausted %d retries. Aborting today's run.", MAX_RETRIES)
        return 1

    assert spec is not None
    repo_url, pages_url = publish(spec, WORKSPACE, gh_token)
    log.info("Published: %s", repo_url)
    if pages_url:
        log.info("Pages:     %s", pages_url)
    update_memory(memory, spec, repo_url, pages_url, errors)

    owner = Github(gh_token).get_user().login
    render_dashboard(memory, owner=owner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
