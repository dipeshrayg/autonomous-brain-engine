"""
dashboard.py - Render the master repo's README + index.html from memory_log.

Both files are regenerated from scratch every run, so they stay perfectly in
sync with memory_log.json. The README is what GitHub renders on the repo
front page; index.html is what GitHub Pages serves.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("brain.dashboard")

README_PATH = Path("README.md")
INDEX_PATH = Path("index.html")

# Static dashboard HTML — fetches memory_log.json client-side so it's always
# fresh without needing a JS build step.
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Autonomous Brain - Daily Creations</title>
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

<footer>Updates daily 06:17 UTC · <a href="memory_log.json">memory_log.json</a></footer>

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


def render_dashboard(memory: dict[str, Any], owner: str,
                     repo: str = "autonomous-brain") -> None:
    """Regenerate README.md and index.html from memory_log."""
    projects = list(reversed(memory.get("projects", [])))
    total = len(projects)
    avg = (sum(p.get("complexity_score", 0) for p in projects) / total) if total else 0.0
    languages = sorted({p.get("language", "?") for p in projects if p.get("language")})
    latest = projects[0]["date"] if projects else "—"

    rows: list[str] = []
    for p in projects[:30]:
        concepts = ", ".join((p.get("concepts_demonstrated") or [])[:3])
        gh_path = (p.get("repo_url") or "").replace("https://github.com/", "")
        cs_url = f"https://codespaces.new/{gh_path}" if gh_path else ""
        run_links: list[str] = []
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

    readme = (
        f"# 🤖 Autonomous Brain\n\n"
        f"A self-improving AI software-engineering pipeline. Every day at 06:17 UTC, a\n"
        f"GitHub Action wakes up, asks an LLM (free GitHub Models) to design a brand-new\n"
        f"browser-runnable project that's more advanced than yesterday's. The pipeline:\n\n"
        f"1. **Plan** — architect the project at the design level.\n"
        f"2. **Implement** — generate each file in its own LLM call.\n"
        f"3. **Critique + Browser-verify** — review with senior-engineer prompt + run the\n"
        f"   page in real headless Chrome to detect blank canvases, JS errors, missing\n"
        f"   controls, and so on.\n"
        f"4. **Fix** — feed every issue back to the LLM and iterate (up to 3 cycles).\n"
        f"5. **Polish** — final pass for visual quality, animations, accessibility.\n"
        f"6. **Final-verify + publish** — confirm the polished version still works, then\n"
        f"   create a public repo and enable GitHub Pages.\n\n"
        f"📊 **Live dashboard:** https://{owner}.github.io/{repo}/\n"
        f"🔁 **Schedule:** daily 06:17 UTC (backup 18:17 UTC) · **Cost:** $0 · **Source:** [`brain.py`](brain.py)\n\n"
        f"## Stats\n\n"
        f"- **Total projects:** {total}\n"
        f"- **Average complexity:** {avg:.1f} / 10\n"
        f"- **Latest run:** {latest}\n"
        f"- **Languages explored:** {', '.join(languages) if languages else '—'}\n\n"
        f"## Latest creations\n\n"
        f"| Date | Project | Lang | ★ | Concepts | Run |\n"
        f"|------|---------|------|---|----------|-----|\n"
        f"{table}\n\n"
        f"---\n\n"
        f"*Generated automatically by `brain.py`. All projects are educational/diagnostic\n"
        f"and TOS-compliant. Last updated {latest}.*\n"
    )

    README_PATH.write_text(readme, encoding="utf-8")
    log.info("README.md regenerated (%d projects).", total)

    INDEX_PATH.write_text(_DASHBOARD_HTML, encoding="utf-8")
    log.info("index.html regenerated.")
