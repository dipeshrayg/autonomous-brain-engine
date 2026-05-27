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


def _count_today(projects: list) -> int:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return sum(1 for p in projects if p.get("date") == today)


def _recent_unique(seq: list, n: int) -> list:
    out: list = []
    for item in reversed(seq):
        if not item:
            continue
        if item in out:
            continue
        out.append(item)
        if len(out) >= n:
            break
    return out

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
  .badge.pattern{background:#1f3a5f;color:#79c0ff}
  .badge.domain{background:#3d2f1f;color:#ffa657}
  .badge.model{background:#2d1b4d;color:#d2a8ff;font-family:ui-monospace,Menlo,monospace;font-size:.7rem}
  .ceo-ribbon{background:linear-gradient(135deg,#1c2333 0%,#2d1b4d 100%);
              border:1px solid #58a6ff;border-radius:10px;padding:1.25rem;margin-bottom:1.5rem}
  .ceo-ribbon.cso{background:linear-gradient(135deg,#1c2c2a 0%,#2a1c33 100%);border-color:#3fb950}
  .ceo-ribbon.cso .ceo-tag{background:#3fb950}
  .badge.security-secure{background:#1c3320;color:#3fb950}
  .badge.security-minor{background:#33301c;color:#f1c40f}
  .badge.security-blocked{background:#3a1c1c;color:#f85149}
  .badge.qa-shippable{background:#1c2c33;color:#79c0ff}
  .badge.qa-partial{background:#33301c;color:#f1c40f}
  .badge.qa-blocked{background:#3a1c1c;color:#f85149}
  .badge.type{background:#2a2a3a;color:#a8b3c7;text-transform:uppercase;
              font-family:ui-monospace,Menlo,monospace;font-size:.7rem;letter-spacing:.5px}
  .ceo-head{display:flex;gap:.75rem;align-items:center;flex-wrap:wrap;margin-bottom:.5rem}
  .ceo-tag{display:inline-block;padding:.15rem .6rem;background:#58a6ff;color:#0d1117;
           font-weight:700;font-size:.75rem;border-radius:4px;letter-spacing:.5px}
  .ceo-verdict{font-weight:700;font-size:1.05rem;text-transform:uppercase;letter-spacing:1px}
  .ceo-verdict.thriving{color:#3fb950}
  .ceo-verdict.acceptable{color:#79c0ff}
  .ceo-verdict.drifting{color:#f1c40f}
  .ceo-verdict.alarming{color:#f85149}
  .ceo-meta{font-size:.8rem;color:#8b949e;margin-left:auto}
  .ceo-body{color:#c9d1d9;font-size:.95rem;margin:.5rem 0;line-height:1.5}
  .ceo-directives{margin:.5rem 0 0;padding-left:1.25rem;color:#c9d1d9;font-size:.9rem}
  .ceo-directives li{margin-bottom:.25rem}
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
<p class="sub">A boardroom of LLMs — a CEO, a Chief Architect, a council of engineers and reviewers — that designs, codes, tests, and ships a new browser project every five hours. Free on GitHub Actions + GitHub Models.<br>
Click <b>▶ Run it</b> to play any project instantly in your browser, or <b>⚡ Codespaces</b> for an in-browser dev environment.<br>
I, Dipesh Ray, believe this is just the smallest concept of what AI is truly capable of. It can simply be given consciousness.</p>

<div id="ceo-ribbon" class="ceo-ribbon" style="display:none">
  <div class="ceo-head">
    <span class="ceo-tag">CEO</span>
    <span class="ceo-verdict" id="ceo-verdict"></span>
    <span class="ceo-meta" id="ceo-meta"></span>
  </div>
  <div class="ceo-body" id="ceo-summary"></div>
  <ul class="ceo-directives" id="ceo-directives"></ul>
</div>

<div id="cso-ribbon" class="ceo-ribbon cso" style="display:none">
  <div class="ceo-head">
    <span class="ceo-tag cso">CSO</span>
    <span class="ceo-verdict" id="cso-verdict"></span>
    <span class="ceo-meta" id="cso-meta"></span>
  </div>
  <div class="ceo-body" id="cso-summary"></div>
  <ul class="ceo-directives" id="cso-directives"></ul>
</div>

<div class="stats">
  <div><div class="stat-num" id="count">—</div><div class="stat-label">Projects</div></div>
  <div><div class="stat-num" id="avg">—</div><div class="stat-label">Avg complexity</div></div>
  <div><div class="stat-num" id="peak">—</div><div class="stat-label">Peak ★</div></div>
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
    document.getElementById('peak').textContent = Math.max(...projects.map(p => p.complexity_score || 0));
    document.getElementById('latest').textContent = projects[0].date;
  }
  // CEO ribbon
  const ceoReviews = (m.ceo_reviews || []);
  if (ceoReviews.length) {
    const last = ceoReviews[ceoReviews.length - 1];
    document.getElementById('ceo-ribbon').style.display = 'block';
    const v = document.getElementById('ceo-verdict');
    v.textContent = last.verdict || '—';
    v.className = 'ceo-verdict ' + (last.verdict || 'acceptable');
    document.getElementById('ceo-meta').textContent =
      `${last.issued_at || ''} · ${last.model || ''}`;
    document.getElementById('ceo-summary').textContent = last.summary || '';
    const ul = document.getElementById('ceo-directives');
    ul.innerHTML = '';
    for (const d of (last.directives || [])) {
      const li = document.createElement('li');
      li.textContent = d;
      ul.appendChild(li);
    }
  }
  // CSO ribbon
  const csoAudits = (m.cso_reviews || m.security_audits || []);
  if (csoAudits.length) {
    const last = csoAudits[csoAudits.length - 1];
    document.getElementById('cso-ribbon').style.display = 'block';
    const v = document.getElementById('cso-verdict');
    v.textContent = last.verdict || '—';
    v.className = 'ceo-verdict ' + (last.verdict || 'acceptable');
    document.getElementById('cso-meta').textContent =
      `${last.issued_at || ''} · ${last.model || ''}`;
    document.getElementById('cso-summary').textContent = last.summary || '';
    const ul = document.getElementById('cso-directives');
    ul.innerHTML = '';
    for (const d of (last.directives || [])) {
      const li = document.createElement('li');
      li.textContent = d;
      ul.appendChild(li);
    }
  }
  const grid = document.getElementById('grid');
  for (const p of projects) {
    const c = document.createElement('div');
    c.className = 'card';
    const concepts = (p.concepts_demonstrated || []).slice(0,4).join(' · ');
    const ghPath = (p.repo_url || '').replace('https://github.com/', '');
    const codespaces = ghPath ? `https://codespaces.new/${ghPath}` : '';
    const patternBadge = p.pattern ? `<span class="badge pattern">${p.pattern}</span>` : '';
    const domainBadge = p.domain ? `<span class="badge domain">${p.domain}</span>` : '';
    const planModel = p.model_attribution && p.model_attribution.plan_judge;
    const modelBadge = planModel ? `<span class="badge model">plan: ${planModel}</span>` : '';
    const projectType = p.project_type || 'web_interactive';
    const typeBadge = `<span class="badge type">${projectType}</span>`;
    const sec = p.security_review || {};
    let secBadge = '';
    if (sec.verdict === 'secure') {
      secBadge = `<span class="badge security-secure" title="Security review: ${sec.findings_count||0} findings">🛡 secure</span>`;
    } else if (sec.verdict === 'minor_concerns') {
      secBadge = `<span class="badge security-minor" title="${sec.findings_count||0} minor findings">🛡 ${sec.findings_count||0} concerns</span>`;
    } else if (sec.verdict === 'publish_blocked') {
      secBadge = `<span class="badge security-blocked" title="Was blocked by CSO and fixed before ship">🛡 fixed at gate</span>`;
    }
    const qa = p.qa_review || {};
    let qaBadge = '';
    if (qa.verdict === 'shippable') {
      qaBadge = `<span class="badge qa-shippable" title="QA: every promised control works">🧪 shippable</span>`;
    } else if (qa.verdict === 'partially_usable') {
      qaBadge = `<span class="badge qa-partial" title="${qa.dead_controls_count||0} dead control(s)">🧪 partial</span>`;
    } else if (qa.verdict === 'non_functional') {
      qaBadge = `<span class="badge qa-blocked" title="QA fixed dead controls before ship">🧪 fixed at gate</span>`;
    }
    c.innerHTML = `
      <h3><a href="${p.repo_url}" target="_blank" rel="noopener">${p.name}</a></h3>
      <div class="meta">${p.date} · <span class="badge">${p.language}</span> <span class="star">★ ${p.complexity_score}</span></div>
      <div class="meta">${typeBadge}${patternBadge}${domainBadge}${modelBadge}${qaBadge}${secBadge}</div>
      <div class="concepts">${concepts}</div>
      <div class="actions">
        ${p.pages_url ? `<a class="btn primary" href="${p.pages_url}" target="_blank" rel="noopener">▶ Run it</a>` : `<a class="btn primary" href="${p.repo_url}#readme" target="_blank" rel="noopener">📄 View</a>`}
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
    for p in projects:
        concepts = ", ".join((p.get("concepts_demonstrated") or [])[:3])
        gh_path = (p.get("repo_url") or "").replace("https://github.com/", "")
        cs_url = f"https://codespaces.new/{gh_path}" if gh_path else ""
        run_links: list[str] = []
        if p.get("pages_url"):
            run_links.append(f"[▶ run]({p['pages_url']})")
        if cs_url:
            run_links.append(f"[⚡ codespaces]({cs_url})")
        run_cell = " · ".join(run_links) if run_links else "—"
        pattern = p.get("pattern", "—")
        domain = p.get("domain", "—")
        rows.append(
            f"| {p.get('date')} | [{p.get('name')}]({p.get('repo_url')}) "
            f"| {p.get('language')} | {p.get('complexity_score')} | {pattern} | {domain} "
            f"| {concepts} | {run_cell} |"
        )
    table = "\n".join(rows) if rows else "| - | _no projects yet_ | - | - | - | - | - | - |"

    # CEO board summary
    ceo_block = ""
    ceo_reviews = memory.get("ceo_reviews", []) or []
    if ceo_reviews:
        last = ceo_reviews[-1]
        ceo_block = (
            f"\n## Latest CEO review\n\n"
            f"**Verdict:** `{last.get('verdict','?')}` — _issued {last.get('issued_at','?')} by {last.get('model','?')}_\n\n"
            f"> {last.get('summary','(no summary)')}\n\n"
            + ("**Active directives** (architect must obey):\n"
               + "\n".join(f"- {d}" for d in last.get('directives', [])) + "\n\n"
               if last.get('directives') else "")
            + ("**Concerns:**\n"
               + "\n".join(f"- {c}" for c in last.get('concerns', [])) + "\n\n"
               if last.get('concerns') else "")
        )

    # failed_builds is stripped by sanitize_memory before public sync;
    # failed_builds_count is preserved as a scalar so the count survives.
    refused_count = memory.get("failed_builds_count", len(memory.get("failed_builds", [])))
    type_counts: dict[str, int] = {}
    for p in projects:
        pt = p.get("project_type", "web_interactive")
        type_counts[pt] = type_counts.get(pt, 0) + 1
    type_summary = ", ".join(
        f"{pt} ({n})" for pt, n in sorted(type_counts.items(), key=lambda x: -x[1])
    ) or "-"

    readme = (
        f"# Autonomous Brain\n\n"
        f"A zero-cost, fully autonomous multi-agent AI pipeline that continuously conceives,\n"
        f"architects, implements, quality-assures, and publishes novel software projects\n"
        f"without any human intervention.\n\n"
        f"**13 AI agents. 3 providers. 0 infrastructure cost. 0 human interventions.**\n\n"
        f"**Live dashboard:** https://{owner}.github.io/{repo}/\n\n"
        f"Every project below is a separate public repository with a live deployed URL.\n\n"
        f"## Stats\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Projects shipped | {total} |\n"
        f"| Builds auto-refused (quality gate) | {refused_count}+ |\n"
        f"| Peak complexity | {max((p.get('complexity_score', 0) for p in projects), default=0)} (open-ended scale) |\n"
        f"| Average complexity | {avg:.1f} |\n"
        f"| Daily cadence | Up to 5/day, fully autonomous |\n"
        f"| Infrastructure cost | $0 |\n"
        f"| Human interventions | 0 |\n"
        f"| Latest run | {latest} |\n\n"
        f"**Languages explored:** {', '.join(languages) if languages else '-'}  \n"
        f"**Project types shipped:** {type_summary}  \n"
        f"**Domains explored:** {', '.join(_recent_unique([p.get('domain') for p in projects], 8)) or '-'}\n\n"
        f"## Latest creations\n\n"
        f"| Date | Project | Lang | Complexity | Pattern | Domain | Concepts | Run |\n"
        f"|------|---------|------|------------|---------|--------|----------|-----|\n"
        f"{table}\n"
        f"{ceo_block}"
        f"\n## The boardroom - 13 roles, 3 providers\n\n"
        f"Each role uses a different model family for genuinely adversarial perspectives.\n"
        f"All providers are free-tier. Missing API keys are silently skipped.\n\n"
        f"| Role | Model | Provider | Purpose |\n"
        f"|------|-------|----------|---------|\n"
        f"| CEO | `gpt-4o` | GitHub Models | Visionary strategy, domain pivots - runs 4x/day |\n"
        f"| CSO | `llama-3.3-70b-versatile` | Groq | Scientific novelty, algorithmic depth - runs 2x/day |\n"
        f"| CTO | `gemini-2.0-flash` | Google AI Studio | Reads failure logs, patches its own source code |\n"
        f"| Architect A | `mixtral-8x7b-32768` | Groq | Creative planning (Mistral lens) |\n"
        f"| Architect B | `llama-3.3-70b-versatile` | Groq | Creative planning (Meta lens) |\n"
        f"| Judge | `gpt-4o` | GitHub Models | Predictability filter - rejects derivative ideas |\n"
        f"| Engineer | `gpt-4o` | GitHub Models | Per-file implementation with full sibling context |\n"
        f"| Reviewer A | `mixtral-8x7b-32768` | Groq | Code review (Mistral lens) |\n"
        f"| Reviewer B | `gemini-2.0-flash` | Google AI Studio | Code review (Gemini lens) |\n"
        f"| QA Tester | `gpt-4o` | GitHub Models | User-pathway simulation |\n"
        f"| QA Fixer | `gemini-2.0-flash` | Google AI Studio | Repairs dead controls |\n"
        f"| Polisher | `Phi-4` | GitHub Models | UX refinement |\n"
        f"| Fixer | `gpt-4o-mini` | GitHub Models | Iterative repair loop |\n\n"
        f"## How it works\n\n"
        f"```\n"
        f"STAGE 1  ARCHITECT CONFERENCE\n"
        f"         Architect A (Mixtral/Groq) + Architect B (Llama/Groq) propose plans in parallel\n"
        f"         Judge (GPT-4o) synthesises or proposes a more unpredictable plan\n\n"
        f"STAGE 2  IMPLEMENT\n"
        f"         Engineer (GPT-4o) writes each file with full sibling context\n\n"
        f"STAGE 3  QUALITY LOOP (up to 8 rounds)\n"
        f"         Reviewer A (Mixtral/Groq) + Reviewer B (Gemini) in parallel\n"
        f"         Fixer applies merged feedback + Playwright interaction test\n\n"
        f"STAGE 4  QA REVIEW\n"
        f"         Playwright clicks every button, tests every slider\n"
        f"         QA Tester (GPT-4o) issues verdict: shippable / partially_usable / non_functional\n\n"
        f"STAGE 5  PUBLISH\n"
        f"         New public GitHub repo created via API\n"
        f"         GitHub Pages enabled -> live URL in under 60 minutes from cold start\n\n"
        f"STAGE 6  SELF-IMPROVE\n"
        f"         CTO (Gemini) reads last 30 failure logs, proposes a surgical source patch\n"
        f"         Validates Python syntax, commits - next build runs improved code\n"
        f"```\n\n"
        f"## Project types (10 available)\n\n"
        f"| Type | Description |\n"
        f"|------|-------------|\n"
        f"| `web_interactive` | HTML+JS+Canvas browser demos |\n"
        f"| `game_web` | Browser games with rules, state, win condition |\n"
        f"| `python_tool` | Standalone Python programs |\n"
        f"| `generative_art` | Visual output - canvas or SVG |\n"
        f"| `document` | Markdown research articles, styled as web pages |\n"
        f"| `web_3d` | Three.js / WebGL 3D scenes |\n"
        f"| `shader_art` | GLSL fragment shaders, pure WebGL |\n"
        f"| `data_viz` | Python matplotlib/plotly with interactive SVG embed |\n"
        f"| `typescript_app` | TypeScript via esm.sh CDN, no build step |\n"
        f"| `cli_tool` | Rust or Go CLI + Codespaces devcontainer |\n\n"
        f"---\n\n"
        f"*Engine: [autonomous-brain-engine](https://github.com/{owner}/autonomous-brain-engine) - "
        f"ORCID: [0009-0001-9970-0220](https://orcid.org/0009-0001-9970-0220) - "
        f"Built by Dipesh Ray - Infrastructure cost: $0 - Last updated {latest}.*\n"
    )

    README_PATH.write_text(readme, encoding="utf-8")
    log.info("README.md regenerated (%d projects).", total)

    INDEX_PATH.write_text(_DASHBOARD_HTML, encoding="utf-8")
    log.info("index.html regenerated.")
