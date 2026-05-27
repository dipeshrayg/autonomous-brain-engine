from pathlib import Path

readme = """\
# Autonomous Brain - Engine

The orchestrator that drives the public showcase at
[dipeshrayg.github.io/autonomous-brain](https://dipeshrayg.github.io/autonomous-brain/).

A zero-cost, fully autonomous multi-agent LLM pipeline that continuously conceives,
architects, implements, quality-assures, and publishes novel software projects
without any human intervention.

**Total infrastructure cost: $0**

---

## Live stats

| Metric | Value |
|---|---|
| Projects shipped | 34+ |
| Refused builds | 108+ |
| Complexity range | 3 to 52 (open-ended, no cap) |
| Project types available | 10 types |
| Project types shipped so far | 6 types |
| AI models in boardroom | 13 roles across 3 providers |
| Providers | GitHub Models + Groq + Google AI Studio |
| Daily builds | Up to 5/day, fully autonomous |
| Human interventions required | 0 |

---

## Architecture

### Infrastructure (all free-tier)

| Layer | Resource |
|---|---|
| Compute | GitHub Actions (public repo = unlimited minutes) |
| LLM inference | GitHub Models API + Groq + Google AI Studio |
| Hosting | GitHub Pages (static, unlimited bandwidth) |
| Storage | GitHub repos + memory_log.json |

### The Boardroom: 13 roles, 3 providers

Each role uses a different model family so the adversarial conference
produces genuinely diverse perspectives. Groq is used for Mistral and Meta
models due to its ultra-fast free-tier inference:

| Role | Model | Provider | Purpose |
|---|---|---|---|
| CEO | gpt-4o | GitHub Models | Visionary strategy, domain pivots |
| CSO | llama-3.3-70b-versatile | Groq | Scientific novelty, algorithmic depth |
| CTO | gemini-2.0-flash | Google AI Studio | Self-improvement, code patches |
| Architect A | mixtral-8x7b-32768 | Groq | Creative planning (Mistral lens) |
| Architect B | llama-3.3-70b-versatile | Groq | Creative planning (Meta lens) |
| Judge | gpt-4o | GitHub Models | Predictability filter |
| Engineer | gpt-4o | GitHub Models | Per-file implementation |
| Reviewer A | mixtral-8x7b-32768 | Groq | Code review (Mistral lens) |
| Reviewer B | gemini-2.0-flash | Google AI Studio | Code review (Gemini lens) |
| QA Tester | gpt-4o | GitHub Models | User-pathway simulation |
| QA Fixer | gemini-2.0-flash | Google AI Studio | Repairs dead controls |
| Polisher | Phi-4 | GitHub Models | UX refinement |
| Fixer | gpt-4o-mini | GitHub Models | Iterative repair |

All roles have gpt-4o / gpt-4o-mini as guaranteed final fallback.
Missing API keys are silently skipped - the pipeline never crashes.
Groq provides the Mistral (Mixtral) and Meta (Llama) perspectives at zero cost.

### Pipeline stages

```
STAGE 1    ARCHITECT CONFERENCE
           Candidate A (Mixtral/Groq) + Candidate B (Llama/Groq) propose plans in parallel
           Validator: banned types, repeated patterns, complexity floor, novel concept check
           Judge (GPT-4o) synthesises or proposes its own unpredictable plan

STAGE 2    IMPLEMENT
           Engineer (GPT-4o) writes each file with full sibling context
           Encoding rules enforced: UTF-8 charset meta, utf-8 open() calls

STAGE 3+4  QUALITY LOOP (up to 8 rounds)
           Reviewer A (Mixtral/Groq) + Reviewer B (Gemini) in parallel
           Fixer applies merged feedback
           Playwright interaction test after each round

STAGE 5    POLISH (with rollback)
           Polisher (Phi-4) refines UX; rolled back if quality regresses

STAGE 6    FINAL VERIFY
           Playwright: page load, canvas render, control interaction tests
           WebGL pixel sampling for 3D/shader projects
           Console error analysis (noise-filtered)

STAGE 6.4  QA REVIEW
           QA Tester (GPT-4o) verdict; up to 3 rounds with QA Fixer (Gemini)
           Ships with partially_usable badge if residual issues remain

STAGE 7    PUBLISH
           New public GitHub repo created via API
           GitHub Pages enabled -> live URL

STAGE 8    MEMORY + DASHBOARD
           memory_log.json updated; public dashboard regenerated
```

### Autonomous workflows

| Workflow | Schedule | Purpose |
|---|---|---|
| daily_build.yml | 9x/day cron | Main build pipeline |
| watchdog.yml | Every 30 min | Dispatches builds if idle >5h |
| ceo_review.yml | 4x/day | CEO strategy + directives |
| science_review.yml | 2x/day | CSO scientific depth audit |
| self_improve.yml | After CEO + 2x/day | CTO patches its own source code |

### Project types (10)

| Type | Description | Verifier | Status |
|---|---|---|---|
| web_interactive | HTML+JS+Canvas browser demos | Playwright | Active (15 shipped) |
| game_web | Browser games with rules + state | Playwright | Active (5 shipped) |
| python_tool | Standalone Python programs | Subprocess | Active (6 shipped) |
| generative_art | Visual output (canvas/SVG) | Playwright | Active (4 shipped) |
| document | Markdown research/proposals | Structure check | Active (3 shipped) |
| web_3d | Three.js/WebGL scenes | Playwright | Active (1 shipped) |
| shader_art | GLSL fragment shaders, pure WebGL | Playwright | New - targeting |
| data_viz | Python matplotlib/plotly + SVG embed | Subprocess | New - targeting |
| typescript_app | TypeScript via esm.sh CDN | Playwright | New - targeting |
| cli_tool | Rust or Go CLI + Codespaces devcontainer | File check + Playwright | New - targeting |

All types produce an index.html for GitHub Pages.

### Self-improvement (CTO agent)

After every CEO review, self_improve.py:
1. Analyses last 30 failed builds for recurring patterns
2. Extracts only the relevant pipeline section (within 8k token API limit)
3. Proposes one surgical old_string/new_string patch (Gemini primary, GPT-4o fallback)
4. Validates Python syntax with ast.parse() before writing
5. Commits the patch - next build runs improved code automatically
6. Logs all improvements to memory_log.json (never re-applies the same fix)

### Quality gates

- **Type ban system**: any project type that fails 3+ times consecutively is auto-banned until a different type ships
- **Complexity floor**: each plan must meet a minimum complexity threshold (rises with type history)
- **Novel concept check**: plan must introduce at least one concept not in the last 14 projects
- **Predictability filter**: Judge rejects derivative ideas before any code is written
- **Interaction test**: Playwright clicks every button and slider, flags dead controls before ship
- **QA verdict**: LLM simulates user pathways and issues shippable / partially_usable / non_functional verdict

---

## Key files

| File | Purpose |
|---|---|
| brain.py | Main orchestrator - all pipeline stages |
| pipeline.py | LLM prompts + plan validation + type logic |
| verifier.py | Playwright verification + Python subprocess runner |
| executive.py | CEO + CSO meta-review agents |
| self_improve.py | CTO self-improvement agent |
| roles.py | Multi-provider model registry + resilient call chain |
| dashboard.py | HTML dashboard generator |
| publish_public.py | Pushes dashboard to public GitHub Pages repo |
| memory_log.json | Persistent state: projects, failures, all reviews |
| generate_paper.py | ReportLab PDF generator for the research paper |
| research_paper.md | Research paper source (markdown) |
| Dipesh_Ray_Autonomous_Brain_Research_Paper.pdf | Published research paper |

---

## Setup

### Required secrets

| Secret | Where to get it | Required |
|---|---|---|
| GH_PAT | GitHub > Settings > Developer Settings > PAT (repo scope) | Yes |
| GROQ_API_KEY | console.groq.com > API Keys | Recommended (free, provides Llama + Mixtral) |
| GOOGLE_AI_KEY | aistudio.google.com > Get API Key | Recommended (free, provides Gemini) |

GITHUB_TOKEN is provided automatically by GitHub Actions.
If GROQ_API_KEY or GOOGLE_AI_KEY are absent, those models are silently
skipped and the pipeline falls back to gpt-4o / gpt-4o-mini.

### Run locally

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
export GITHUB_TOKEN=ghp_...   # needs models:read scope (Actions token only)
export GH_PAT=ghp_...         # needs repo scope
export GROQ_API_KEY=gsk_...   # optional, free at console.groq.com
export GOOGLE_AI_KEY=AIza...  # optional, free at aistudio.google.com
python brain.py
```

Note: local GITHUB_TOKEN does not have the models:read scope that GitHub Actions
tokens have automatically. Run via Actions or use a PAT with models scope.

---

## Research

Full research paper documenting 21 days of operation, emergent behaviours,
and system architecture:

- research_paper.md - source text
- Dipesh_Ray_Autonomous_Brain_Research_Paper.pdf - formatted PDF (ReportLab + matplotlib)
- ORCID: https://orcid.org/0009-0001-9970-0220
- Dashboard: https://dipeshrayg.github.io/autonomous-brain/

---

*Built and operated by Dipesh Ray. All infrastructure costs: $0.*
"""

Path("F:/github forever/README.md").write_text(readme, encoding="utf-8")
print("README written:", len(readme), "chars")
