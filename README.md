# Autonomous Brain — Engine (private)

The private orchestrator that drives the public showcase at
[github.com/dipeshrayg/autonomous-brain](https://github.com/dipeshrayg/autonomous-brain)
and its live dashboard at [dipeshrayg.github.io/autonomous-brain](https://dipeshrayg.github.io/autonomous-brain/).

This repo must remain private. The prompts, model routing, CEO/CSO directives,
internal critique transcripts, and full per-project model attribution all live
here. Only sanitized snapshots reach the public side, pushed by
[`publish_public.py`](publish_public.py) at the end of every workflow run.

---

## The pipeline at a glance

Each daily build runs a 7-stage pipeline. Every stage is a separate LLM call
or mechanical check; the next stage only runs if the previous succeeds.

```
PLAN  →  IMPLEMENT  →  CRITIQUE  →  FIX  →  POLISH  →  SECURITY  →  PUBLISH
```

- **PLAN** — multi-model architect *conference*. Two candidate models propose
  a project plan in parallel; a judge model synthesizes the winner.
- **IMPLEMENT** — one LLM call per file. The Engineer writes each file with
  the plan and sibling files in context.
- **CRITIQUE** — multi-model reviewer *conference*. Two reviewers find bugs in
  parallel; their must-fix lists merge; most-pessimistic verdict wins.
- **FIX** — Fixer applies the merged issues. Quality loop repeats up to 8×.
- **POLISH** — Polisher elevates UX. Has automatic rollback if it regresses.
- **SECURITY** — Chief Security Officer reviews for XSS, prototype pollution,
  CDN integrity, prompt-injection, privacy, deception. Hard veto on
  critical/high findings. One Fixer round granted; if still blocking, refuse
  to publish.
- **PUBLISH** — create new public repo `YYYY-MM-DD-<name>`, push code,
  enable Pages, append to memory, regenerate dashboard, sync to public repo.

---

## The boardroom

A hierarchy of LLMs with distinct roles. Models are routed via [`roles.py`](roles.py)
with explicit fallback chains so per-model rate limits never break the pipeline.

| Role | Primary model | Cadence | Source |
|---|---|---|---|
| **CEO** | gpt-4o | Every 6h | [`executive.py`](executive.py), [`ceo_review.yml`](.github/workflows/ceo_review.yml) |
| **CSO** | gpt-4o | Every 12h | [`security_officer.py`](security_officer.py), [`security_review.yml`](.github/workflows/security_review.yml) |
| **VP Engineering** (watchdog) | n/a (script) | Every 30 min | [`watchdog.yml`](.github/workflows/watchdog.yml) |
| **Architect — Judge** | gpt-4o | per build | [`pipeline.py`](pipeline.py) `stage_plan` |
| **Architect — Candidate A** | gpt-4o-mini | per build | conference |
| **Architect — Candidate B** | Phi-3.5-MoE | per build | conference |
| **Engineer** | gpt-4o | per file | [`pipeline.py`](pipeline.py) `stage_implement` |
| **Reviewer A** | gpt-4o-mini | per cycle | conference |
| **Reviewer B** | Phi-3.5-MoE | per cycle | conference |
| **Security Officer** | gpt-4o | per build | [`pipeline.py`](pipeline.py) `stage_security_review` |
| **Fixer** | gpt-4o-mini | per cycle | [`pipeline.py`](pipeline.py) `stage_fix` |
| **Polisher** | gpt-4o-mini | once | [`pipeline.py`](pipeline.py) `stage_polish` |
| **QA** | Playwright + Chromium | per cycle | [`verifier.py`](verifier.py) |

Both the CEO and CSO write directives into `memory_log.json`; the next
architect prompt receives the union of the most recent CEO and CSO
directives, both of which it must obey.

---

## Files

| File | Job |
|---|---|
| [`brain.py`](brain.py) | Orchestrator — the slim entry point, runs the 7-stage pipeline. |
| [`pipeline.py`](pipeline.py) | All LLM stage functions, prompts, plan validator. |
| [`verifier.py`](verifier.py) | Playwright + Chromium real-browser verification. Detects blank canvas, runaway resize, dangling references, missing controls, console/page errors. |
| [`executive.py`](executive.py) | CEO periodic trajectory review. |
| [`security_officer.py`](security_officer.py) | CSO periodic security audit. |
| [`roles.py`](roles.py) | Model registry, role→model map, resilient `call_with_fallback`. |
| [`dashboard.py`](dashboard.py) | Generates public-facing README + index.html from the ledger. |
| [`publish_public.py`](publish_public.py) | Sanitizes memory + cross-repo push to the public dashboard. |
| [`memory_log.json`](memory_log.json) | Full history: every project, CEO review, CSO audit, with model attribution. Engine-only fields are stripped before reaching public. |
| `.github/workflows/` | All four scheduled workflows. |

---

## Schedules

| Workflow | Cadence (UTC) | Job |
|---|---|---|
| **Daily Build** | 9 staggered crons; ≥5h spacing; ≤5 projects/day | The full pipeline |
| **Watchdog** | every 30 min | Force-dispatch when below target; quiet hours 23-02 UTC |
| **CEO Review** | 01:11 / 07:11 / 13:11 / 19:11 | Trajectory review + directives |
| **Security Review** | 04:29 / 16:29 | Security audit + directives |

Every workflow that mutates `memory_log.json` ends with a **Sync public
dashboard** step that runs `publish_public.py` to push a sanitized snapshot
to the public repo. `continue-on-error: true` means a transient sync hiccup
just retries on the next workflow tick.

---

## Memory schema

Per-project records carry:

- `name`, `date`, `completed_at_unix`, `repo_url`, `pages_url`, `language`
- `complexity_score` (open scale, no cap)
- `pattern` (visualizer / dashboard / generator / …) and `domain` (must
  rotate from last 5)
- `concepts_demonstrated`, `novel_concepts`, `advancement_axis`
- `tech_stack`, `visual_identity`
- `file_count`, `loc`, `quality_cycles_used`
- `final_verify_metrics` (canvas, controls, etc.)
- **`model_attribution`** (private-only) — which model did the plan judging,
  which were the candidates, which model implemented each file
- **`ceo_directives_followed`** (private-only) — verbatim CEO directives
  active for that build
- **`security_review`** — verdict + count + full findings array

Top-level: `projects[]`, `ceo_reviews[]`, `security_audits[]`,
`complexity_trajectory[]`, `concepts_explored[]`, `patterns_used[]`,
`domains_used[]`.

---

## Secrets required

| Secret | Where | Why |
|---|---|---|
| `GH_PAT` | engine repo (and public repo, kept in sync) | Fine-grained PAT, scoped All-repos with Administration:write, Contents:write, Pages:write, Workflows:write, Metadata:read. Used to create new daily project repos AND to push the dashboard to the public repo. |
| `GITHUB_TOKEN` | auto-injected | `models: read` for LLM calls, `contents: write` for memory commits, `actions: write` for watchdog dispatch. |

---

## Operational notes

- **Cost: $0** as long as we stay within free-tier rate limits on both
  GitHub Models (per-model daily caps) and GitHub Actions
  (private repos: 2000 min/month — current projection ~1700).
- **PAT rotation** is the only manual touch the system needs. The PAT
  expires per its `Expiration` setting; rotate via:
  ```
  gh secret set GH_PAT --repo dipeshrayg/autonomous-brain-engine
  gh secret set GH_PAT --repo dipeshrayg/autonomous-brain
  ```
- **Pause everything**: disable `daily_build.yml` and `watchdog.yml` via
  `gh api -X PUT repos/dipeshrayg/autonomous-brain-engine/actions/workflows/<file>/disable`.
  CEO + Security Review can stay running — they don't depend on the PAT.

---

## Public face (what outsiders see)

The public repo at [dipeshrayg/autonomous-brain](https://github.com/dipeshrayg/autonomous-brain)
contains only:

- `README.md` — a project showcase with no engine internals
- `index.html` — the live dashboard (renders cards from `memory_log.json`)
- `memory_log.json` — sanitized snapshot
- `SECURITY.md` — security policy

Pushed automatically by every engine workflow run. The Pages URL never
breaks during normal operation.

The daily project repos (`dipeshrayg/YYYY-MM-DD-*`) are also public — those
are intentional outputs, the playable demos visitors come for.
