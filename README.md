# Autonomous Brain - Engine

### ▶ Live Dashboard: **https://dipeshrayg.github.io/autonomous-brain-engine/**

Featured Projects:
1. https://dipeshrayg.github.io/2026-07-16-symbiotic-neural-networks/
2. https://dipeshrayg.github.io/2026-07-30-stellar-odyssey/
3. https://dipeshrayg.github.io/2026-07-29-sdf-fractal-explorer/
4. https://dipeshrayg.github.io/2026-07-28-cryptography-workbench/

A React + Supabase dashboard with a **public project showcase** and **auth-gated**
operational logs (failure logs, executive reviews, raw build stream), backed by a
Postgres database with row-level security enforced on every table.

A zero-cost, fully autonomous multi-agent LLM pipeline that continuously conceives,
architects, implements, quality-assures, and publishes novel software projects
without any human intervention.

**Total infrastructure cost: $0** — GitHub Actions (compute) + Groq + Google AI Studio
(LLMs) + Supabase free tier (database) + GitHub Pages (hosting).

---

## Live stats

| Metric | Value |
|---|---|
| Projects shipped | 187+ |
| Refused builds | 656+ |
| Peak complexity score | 3,000 |
| Average complexity | 808 |
| Project types available | 21 types |
| AI models in boardroom | 13 roles across 2 providers |
| Providers | Groq + Google AI Studio |
| Database | Supabase (Postgres + RLS), online & auth-secured |
| Frontend | React (Vite) on GitHub Pages |
| Active since | April 28, 2026 |
| Active days | 81+ |
| Daily builds | Up to 5/day, fully autonomous |
| Human interventions required | 0 |

---

## Architecture

### Infrastructure (all free-tier)

| Layer | Resource |
|---|---|
| Compute | GitHub Actions (public repo = unlimited minutes) |
| LLM inference | Groq + Google AI Studio |
| Hosting | GitHub Pages (static, unlimited bandwidth) |
| Database | Supabase (Postgres, RLS-secured) |
| Storage | GitHub repos + memory_log.json |

### The Boardroom: 13 roles, 2 providers

Each role uses a different model family so the adversarial conference produces
genuinely diverse perspectives. Groq (Meta Llama + Qwen) and Google (Gemini) are
the two active providers — both free tier, zero cost.

| Role | Primary Model | Provider | Purpose |
|---|---|---|---|
| CEO | llama-3.3-70b-versatile | Groq | Visionary strategy, domain pivots |
| CSO | llama-3.3-70b-versatile | Groq | Scientific novelty, algorithmic depth |
| CTO | gemini-2.0-flash | Google | Self-improvement, code patches |
| Architect A | llama-4-scout-17b | Groq | Creative planning (Llama 4 lens) |
| Architect B | qwen3-32b | Groq | Creative planning (Qwen lens — different family) |
| Judge | gemini-2.0-flash | Google | Predictability filter (Google = independent from Groq candidates) |
| Engineer | gemini-2.0-flash | Google | Per-file implementation (large context) |
| Reviewer A | llama-3.3-70b-versatile | Groq | Code review (Llama lens) |
| Reviewer B | gemini-2.0-flash-lite | Google | Code review (lightweight Gemini) |
| QA Tester | llama-3.3-70b-versatile | Groq | User-pathway simulation |
| QA Fixer | gemini-2.0-flash | Google | Repairs dead controls |
| Fixer | llama-3.1-8b-instant | Groq | Fast iterative repair |
| Polisher | gemini-2.0-flash-lite | Google | UX refinement |

All roles have multiple Groq + Google fallbacks. Missing API keys are silently
skipped — the pipeline never crashes due to a missing key.

### Pipeline stages

```
STAGE 1    ARCHITECT CONFERENCE
           Candidate A (Llama 4/Groq) + Candidate B (Qwen/Groq) propose plans in parallel
           Validator: banned types, repeated patterns, complexity floor/ceiling, novel concept check,
                      complexity_justification (3+ algorithmic challenges required), visual theme rotation
           Judge (Gemini/Google) synthesises or proposes its own unpredictable plan

STAGE 2    IMPLEMENT
           Engineer (Gemini/Google) writes each file with full sibling context
           Encoding rules enforced: UTF-8 charset meta, utf-8 open() calls

STAGE 3+4  QUALITY LOOP (up to 8 rounds)
           Reviewer A (Llama/Groq) + Reviewer B (Gemini-lite/Google) in parallel
           Fixer applies merged feedback
           Playwright interaction test after each round

STAGE 5    POLISH (with rollback)
           Polisher (Gemini-lite) refines UX; rolled back if quality regresses

STAGE 6    FINAL VERIFY
           Playwright: page load, canvas render, control interaction tests
           WebGL pixel sampling for 3D/shader projects
           Console error analysis (noise-filtered)

STAGE 6.4  QA REVIEW
           QA Tester (Llama/Groq) verdict; up to 3 rounds with QA Fixer (Gemini)
           Ships with partially_usable badge if residual issues remain

STAGE 7    PUBLISH
           New public GitHub repo created via API
           GitHub Pages enabled -> live URL

STAGE 8    MEMORY + DASHBOARD
           memory_log.json committed to git; Supabase synced; dashboard regenerated
```

### Autonomous workflows

| Workflow | Schedule | Purpose |
|---|---|---|
| daily_build.yml | 9x/day cron | Main build pipeline |
| watchdog.yml | Every 30 min | Dispatches builds if idle >5h |
| ceo_review.yml | 4x/day | CEO strategy + directives |
| science_review.yml | 2x/day | CSO scientific depth audit |
| self_improve.yml | After CEO + 2x/day | CTO patches its own source code |
| deploy_dashboard.yml | On push | Builds React dashboard to GitHub Pages |

### Quality gates (pipeline.py)

- **Complexity justification**: visual types and any project with c>100 must list 3+ specific algorithmic challenges — not bypassed even in recovery mode (honesty gate)
- **Complexity floor/ceiling**: floor is `type_max − 20` (modest regression allowed); ceiling is `type_max + 40` per step (prevents score inflation)
- **Visual theme**: required for all visual types; rotation enforced between consecutive visual projects
- **Type diversity**: no same project type twice in a row (relaxed in recovery mode)
- **Novel concept check**: plan must introduce concepts not seen in recent projects
- **Predictability filter**: Judge rejects derivative ideas before any code is written
- **Interaction test**: Playwright clicks every button and slider, flags dead controls before ship
- **QA verdict**: LLM simulates user pathways and issues shippable / partially_usable / non_functional

### Self-improvement (CTO agent)

After every CEO review, self_improve.py:
1. Analyses last 30 failed builds for recurring patterns
2. Extracts only the relevant pipeline section (within API context limits)
3. Proposes one surgical patch (Gemini primary, Llama fallback)
4. Validates Python syntax with ast.parse() before writing
5. Commits the patch — next build runs improved code automatically
6. Logs all improvements to memory_log.json (never re-applies the same fix)

---

## Changelog

### August 2026 — Provider migration after GitHub Models retirement

GitHub Models (the free OpenAI API via Azure) was fully retired on **2026-07-30**,
the exact day project shipping stopped. All `gpt-4o`, `gpt-4o-mini`, and `Phi-4`
calls began returning 404. The pipeline was rebuilt on **Groq + Google only**:

- All GitHub Models entries removed from every role chain
- `qwen3-32b` (Groq) added as Architect B — a genuinely different model family
  for real adversarial diversity in the planning conference
- `gemini-2.0-flash` promoted to Judge and Engineer primary (Google perspective
  independent from the Groq-based architect candidates)
- `llama-3.1-8b-instant` used for lightweight roles (Fixer, Polisher)
- 404/401 errors now treated as permanent — no wasted retry attempts

### August 2026 — Complexity inflation fix (pipeline.py)

The `in_recovery` bypass was skipping all meaningful quality gates. At a 21% ship
rate, recovery mode was nearly permanent — meaning the system was building without
justification, without theme enforcement, and with a +1 ratchet that forced
complexity scores to inflate forever regardless of real difficulty:

- `complexity_justification` always required — not bypassed by recovery
- `visual_theme` always required and rotation always enforced
- Complexity floor changed from `max + 1` (ratchet) to `max − 20` (regression allowed)
- Complexity ceiling added: `max + 40` per step — prevents score jumping to fake advancement

---

## Key files

| File | Purpose |
|---|---|
| brain.py | Main orchestrator — all pipeline stages |
| pipeline.py | LLM prompts + plan validation + type logic + quality gates |
| verifier.py | Playwright verification + Python subprocess runner |
| executive.py | CEO + CSO meta-review agents |
| self_improve.py | CTO self-improvement agent |
| roles.py | Multi-provider model registry + resilient fallback chains |
| supabase_sync.py | Best-effort Supabase mirror (never blocks a build) |
| dashboard.py | HTML dashboard generator |
| publish_public.py | Pushes dashboard to public GitHub Pages |
| memory_log.json | Persistent state: all projects, failures, reviews |

---

## Setup

### Required secrets

| Secret | Where to get it | Required |
|---|---|---|
| GH_PAT | GitHub > Settings > Developer Settings > PAT (repo scope) | Yes |
| GROQ_API_KEY | console.groq.com > API Keys | Yes (primary inference provider) |
| GOOGLE_AI_KEY | aistudio.google.com > Get API Key | Yes (engineer + judge primary) |
| SUPABASE_URL | Supabase project settings > API | Yes (live dashboard) |
| SUPABASE_SERVICE_ROLE_KEY | Supabase project settings > API | Yes (write access) |
| SUPABASE_ANON_KEY | Supabase project settings > API | Yes (dashboard frontend) |

GITHUB_TOKEN is provided automatically by GitHub Actions (used for git push and
repo creation only — GitHub Models API was retired 2026-07-30).

### Run locally

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
export GH_PAT=ghp_...           # needs repo scope
export GROQ_API_KEY=gsk_...     # free at console.groq.com
export GOOGLE_AI_KEY=AIza...    # free at aistudio.google.com
python brain.py
```

---

## Research

Full research paper documenting the system architecture, emergent behaviours,
and empirical results:

- research_paper.md — source text (Markdown)
- ORCID: https://orcid.org/0009-0001-9970-0220

---

*Built and operated by Dipesh Ray, Ulster University. All infrastructure costs: $0.*
