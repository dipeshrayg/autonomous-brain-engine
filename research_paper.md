# Autonomous Multi-Agent LLM Pipeline for Continuous Software Creation: Architecture, Findings, and Emergent Behaviours

**Author:** Dipesh Ray  
**Date:** May 2026  
**Repository:** https://github.com/dipeshrayg/autonomous-brain-engine  
**Dashboard:** https://dipeshrayg.github.io/autonomous-brain/

---

## Abstract

This paper presents the design, implementation, and empirical findings of an autonomous multi-agent Large Language Model (LLM) pipeline that continuously conceives, architects, implements, quality-assures, and publishes novel software projects without human intervention. The system, named *Autonomous Brain*, operates entirely on free-tier infrastructure — GitHub Actions for compute, GitHub Models API for LLM inference, and GitHub Pages for deployment — with a total operational cost of $0. Over a 21-day observation period the pipeline shipped 27 projects spanning five distinct project types (web applications, Python tools, browser games, generative art, and research documents), at complexity scores ranging from 3 to 42 on an open-ended scale, with 90 refused builds recorded and analysed. The work demonstrates that hierarchical LLM role specialisation, failure-aware memory, and automated quality gates can produce a self-improving, self-healing creative pipeline at zero marginal cost. Key emergent behaviours — including CEO strategy pivots in response to failure data, autonomous type bans, and recovery mode — are documented.

---

## 1. Introduction

The rapid improvement of large language models has prompted significant interest in *agentic* systems: pipelines where multiple LLM calls are chained together to accomplish multi-step tasks. Most prior work focuses on single-domain agentic loops (code completion, bug fixing, web browsing). This work explores a different question: **can a hierarchical multi-agent LLM system autonomously create diverse, novel software projects continuously, without human prompting, on free-tier infrastructure?**

The motivation is twofold. First, practically: many researchers and hobbyists lack the budget for commercial AI APIs. Second, scientifically: studying what such a system produces over time — and where it gets stuck — reveals interesting properties of LLM-based creative autonomy.

The contributions of this work are:

1. A complete open-source autonomous software-creation pipeline running on free infrastructure.
2. A hierarchical role architecture (CEO, CSO, Architect Judge, Engineer, Reviewer Conference, QA Tester, QA Fixer) with distinct personas and adversarial disagreement encouraged.
3. An empirical record of 27 shipped projects and 90 refused builds over 21 days.
4. Documentation of emergent system behaviours: failure-driven strategy pivots, complexity escalation, domain rotation, type bans, and self-healing recovery.
5. A novel *Project Evolution* mandate that expands the system beyond web applications into Python tools, browser games, generative art, and research documents.

---

## 2. System Architecture

### 2.1 Infrastructure

The entire system runs on GitHub's free tier:

| Component | Free-tier resource |
|---|---|
| Compute | GitHub Actions (public repo: unlimited minutes) |
| LLM inference | GitHub Models API (gpt-4o + gpt-4o-mini) |
| Hosting | GitHub Pages (static, unlimited bandwidth) |
| Storage | GitHub repositories + JSON memory log |
| **Total cost** | **$0** |

### 2.2 Agent Roles

The pipeline implements a boardroom metaphor with nine specialised roles:

**Executive layer:**
- **CEO** (gpt-4o): Visionary strategist. Reviews shipped projects and refused builds every 36 hours. Issues directives demanding domain shifts, complexity escalation, and type diversity. Verdict scale: `thriving → acceptable → drifting → alarming`.
- **CSO** (gpt-4o): Chief Science Officer. Reviews for algorithmic novelty and experimental edge-cases. Pushes for physics simulations, novel algorithms, mathematical depth.

**Planning layer:**
- **Architect Candidate A/B** (gpt-4o-mini): Two independent architects propose plans in parallel at temperature=1.0.
- **Judge** (gpt-4o): Applies a single filter — *"Is this predictable?"* — and either selects the strongest candidate, synthesises a hybrid, or proposes its own plan if all candidates are too safe.

**Implementation layer:**
- **Engineer** (gpt-4o): Implements files one by one, with full context of sibling files already written.
- **Reviewer A/B** (gpt-4o-mini): Parallel review conference producing fix/redo/ship verdicts.
- **Fixer** (gpt-4o-mini): Applies targeted repairs based on merged reviewer feedback.

**Quality layer:**
- **Polisher** (gpt-4o-mini): Final UX and code quality pass with rollback protection.
- **QA Tester** (gpt-4o): Reviews mechanical verification results (Playwright interaction tests, canvas render checks, console error analysis). Returns structured JSON with `dead_controls`, `missing_features`, `state_sync_issues`.
- **QA Fixer** (gpt-4o): Repairs issues flagged by the tester.

### 2.3 Pipeline Stages

```
STAGE 1: ARCHITECT CONFERENCE
  → 2 candidates proposed in parallel (temperature=1.0)
  → Validator rejects plans below complexity floor, missing files,
    repeated patterns/domains/types, banned types
  → Judge synthesises if ≥2 candidates pass

STAGE 2: IMPLEMENT
  → Engineer writes each file sequentially with full sibling context

STAGE 3+4: QUALITY LOOP (up to 3 rounds)
  → Reviewer A + B conference in parallel
  → Fixer applies merged feedback
  → Playwright mechanical verification after each round

STAGE 5: POLISH (with rollback)
  → Polisher refines UX
  → Rolled back if post-polish problem count exceeds pre-polish

STAGE 6: FINAL VERIFY
  → Playwright: page load, canvas render, control interaction tests
  → Console error analysis (noise-filtered)

STAGE 6.4: QA REVIEW
  → LLM Tester verdict (up to 3 rounds with QA Fixer)
  → Ships with 'partially_usable' badge if residual issues remain

STAGE 7: PUBLISH
  → New public GitHub repository created
  → GitHub Pages enabled (index.html required for ALL project types)
  → Memory log updated

STAGE 8: MEMORY + DASHBOARD
  → Project record appended to memory_log.json
  → Public dashboard regenerated
```

### 2.4 Project Types

The *Project Evolution* mandate expanded the system beyond web applications:

| Type | Description | Verifier |
|---|---|---|
| `web_interactive` | HTML+JS+Canvas browser demos | Playwright |
| `web_3d` | Three.js/WebGL scenes | Playwright |
| `game_web` | Browser games with rules + state | Playwright |
| `generative_art` | Visual output (canvas/SVG) | Playwright |
| `python_tool` | Standalone Python programs | Subprocess |
| `document` | Markdown research/proposals | Structure check |

All types produce an `index.html` for GitHub Pages — even Python tools and documents generate a visual showcase page so users can experience the project directly from the dashboard.

### 2.5 Memory and Directives

The system maintains a persistent `memory_log.json` with:
- All shipped projects (complexity, type, domain, pattern, QA verdict, timestamps)
- All refused builds (plan name, type, failure reason, dead controls)
- CEO review records (verdict, directives, model)
- CSO review records (experimental directives)
- `concepts_explored[]` list (prevents repetition)

This memory is read by every agent at the start of each run, creating a genuine long-term learning loop.

---

## 3. Key Mechanisms

### 3.1 Complexity Escalation

Each project must exceed the maximum complexity score of all recent projects. The scale is open-ended (no cap). Complexity rose from 3 (initial runs) to 42 over the observation period. In recovery mode (≥3 consecutive failures since last ship), the complexity floor is relaxed to ensure something ships.

### 3.2 Type Diversity Enforcement

After the system became stuck producing only `web_interactive` projects, a type diversity engine was added:

- **Cannot repeat the same type twice in a row**
- **Complexity ceilings per type** (e.g., `document`=35, `python_tool`=60)
- **Type ban system**: if a type fails 3+ times consecutively, it is automatically banned until the next successful ship
- **CEO diversity mandate**: CEO reads a TYPE DIVERSITY REPORT showing counts, maxed types, and recommended next types

### 3.3 Self-Healing via Type Bans

The most significant emergent behaviour observed was the `web_3d` failure loop (May 10–11): 18 consecutive failed builds, all attempting Three.js projects that produced blank canvases or broken controls. The system had no escape mechanism.

The type ban system was introduced to solve this: after 3 failures of the same type, the validator hard-blocks that type. The CEO receives the ban list and its prompt instructs it to pivot. On the next build after activation, the CEO verdict shifted from `drifting` to `alarming` and directives immediately switched to `document` type. The first post-ban build shipped successfully on the first attempt.

### 3.4 Watchdog Autonomy

A separate workflow (`watchdog.yml`) runs every 30 minutes, reads the memory log, and dispatches a new build if:
- Fewer than 5 projects shipped today
- ≥5 hours have elapsed since the last ship
- No build is currently running/queued
- Fewer than 8 dispatches already today (runaway protection)

This means the system operates continuously without any human trigger.

---

## 4. Results

### 4.1 Overview (21-day period, April 28 – May 18, 2026)

| Metric | Value |
|---|---|
| Total projects shipped | 27 |
| Total refused builds | 90 |
| Ship rate | 23% (27 / 117 build attempts) |
| Complexity range | 3 – 42 |
| Average complexity | 20.7 |
| Peak complexity | 42 |
| Project types shipped | 5 of 6 (`web_3d` banned at time of writing) |
| Days active | 21 |
| Total cost | $0 |

### 4.2 Type Distribution

| Type | Shipped | Notes |
|---|---|---|
| `web_interactive` | 15 | Baseline, shipped reliably |
| `python_tool` | 3 | Introduced in Project Evolution |
| `document` | 3 | Markdown + styled HTML showcase |
| `game_web` | 3 | 4 failed before canvas guidance added |
| `generative_art` | 3 | High QA pass rate |
| `web_3d` | 0 | Banned after 18 consecutive failures |

### 4.3 Quality Gate Performance

The QA gate (mechanical Playwright verification + LLM Tester review) refused 90 builds. The most common failure modes:

1. **Blank canvas** (35% of failures): Canvas element exists but renders nothing. Fixed by adding explicit width/height and immediate `requestAnimationFrame` to the engineer prompt.
2. **Dead controls** (28%): Buttons/sliders with no event listeners or broken state updates.
3. **Script load order errors** (18%): Multi-file JS projects where class B references class A before A's script tag.
4. **WebSocket/backend dependencies** (8%): Projects attempting `ws://localhost` connections that don't work on static Pages.
5. **Novel concept exhaustion** (11%): Plans reusing concepts already in `concepts_explored[]`.

### 4.4 CEO Strategy Evolution

Over 21 days, the CEO issued 46 review cycles. Observed verdict trajectory:
- Weeks 1–2: `acceptable` → `drifting` (system too repetitive)
- Project Evolution introduction: CEO pushed for domain shifts
- Post-ban (May 11): `alarming` verdict, immediate pivot to `document`
- Post-recovery: `acceptable`, directives broadened

The CEO demonstrated genuine failure-responsive strategy: directives shifted from "build Python crypto tool" to "build small-scope self-contained game" to "avoid web_3d entirely" as failure data accumulated.

---

## 5. Emergent Behaviours

Several behaviours were not explicitly programmed but emerged from the combination of memory, failure logging, and multi-agent architecture:

**CEO learning loop**: The CEO had no knowledge of refused builds initially. Adding `failed_builds[]` to its context caused it to spontaneously scale back ambition after streaks — without being told to do so.

**Architect recovery**: When the complexity floor is enforced, architects often propose plans slightly above the floor. Over time, this creates consistent escalation without any explicit "increase complexity" instruction.

**Reviewer disagreement utility**: Having Reviewer A and B operate independently at temperature=0.85 means they frequently disagree. A `fix` from one and `ship` from the other produces a merged `fix` verdict, catching issues that a single reviewer might miss.

**Type ban self-healing**: The type ban mechanism converted a stuck system (18 failures, 2 days) into a self-recovering one. After implementation, the first post-ban build shipped on the first attempt. The ban lifts automatically after a successful ship, allowing the type to be retried later.

---

## 6. Limitations and Future Work

**Current limitations:**
- `web_3d` (Three.js) projects remain unshipped — the verification pipeline's canvas render check is too strict for WebGL contexts
- The gpt-4o-mini architect frequently proposes too few files for high-complexity plans, requiring 2 conference rounds
- No persistent inter-run learning beyond the JSON memory log (no vector DB, no embeddings)
- The Playwright verifier cannot test audio output, 3D scene correctness, or Python runtime behaviour beyond subprocess exit codes

**Future directions:**
- Add screenshot-based visual verification using vision models to catch rendering issues before text-based review
- Experiment with more model diversity (Claude, Gemini) via API when budget allows
- Implement a dedicated `web_3d` verifier that checks Three.js scene object counts rather than canvas pixel content
- Extend the system to publish to npm, PyPI, or Hugging Face Hub based on project type
- Study whether complexity escalation converges or continues indefinitely

---

## 7. Conclusion

This work demonstrates that a multi-agent LLM pipeline with hierarchical role specialisation, persistent failure memory, and automated quality gates can continuously produce diverse, novel software projects on entirely free infrastructure. The system shipped 27 projects across 5 domains in 21 days at zero cost, self-healed from a 2-day failure loop autonomously, and showed genuine CEO-level strategy adaptation in response to failure data.

The core insight is that **failure is information**: by making refused builds visible to the strategic layer (CEO), the system developed emergent learning behaviour that no individual component was programmed to exhibit. The combination of adversarial multi-agent critique, mechanical browser verification, and failure-aware memory produced a pipeline that improves its own output quality over time.

The system is fully open-source and operational at https://github.com/dipeshrayg/autonomous-brain-engine.

---

## References

- GitHub Actions documentation: https://docs.github.com/en/actions
- GitHub Models API: https://github.com/marketplace/models
- OpenAI GPT-4o technical report (2024)
- Playwright browser automation: https://playwright.dev
- GitHub Pages: https://pages.github.com

---

*This paper was written by Dipesh Ray and documents original work conducted between April 28 and May 18, 2026.*
