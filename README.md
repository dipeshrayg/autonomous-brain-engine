# 🤖 Autonomous Brain

A self-improving software-engineering pipeline. Every day at 06:17 UTC, a
GitHub Action wakes up, asks an LLM (free GitHub Models) to design a brand-new
browser-runnable project that's more advanced than yesterday's. The pipeline:

1. **Plan** — architect the project at the design level.
2. **Implement** — generate each file in its own LLM call.
3. **Critique + Browser-verify** — review with senior-engineer prompt + run the
   page in real headless Chrome to detect blank canvases, JS errors, missing
   controls, and so on.
4. **Fix** — feed every issue back to the LLM and iterate (up to 3 cycles).
5. **Polish** — final pass for visual quality, animations, accessibility.
6. **Final-verify + publish** — confirm the polished version still works, then
   create a public repo and enable GitHub Pages.

📊 **Live dashboard:** https://dipeshrayg.github.io/autonomous-brain/
🔁 **Schedule:** daily 06:17 UTC (backup 18:17 UTC) · **Cost:** $0 · **Source:** [`brain.py`](brain.py)

## Stats

- **Total projects:** 7 (2 today, target 2/day)
- **Peak complexity:** 11 (open-ended scale, no cap)
- **Average complexity:** 7.6
- **Latest run:** 2026-05-01
- **Languages explored:** JavaScript, Python
- **Patterns used recently:** visualizer
- **Domains explored:** Mathematics

## Latest creations

| Date | Project | Lang | ★ | Pattern | Domain | Concepts | Run |
|------|---------|------|---|---------|--------|----------|-----|
| 2026-05-01 | [differential-equation-visualizer](https://github.com/dipeshrayg/2026-05-01-differential-equation-visualizer) | JavaScript | 11 | visualizer | Mathematics | Numerical solutions of differential equations using the Runge-Kutta method, Interactive parameter adjustment for real-time updates, Dynamic visualization with phase planes and time series | [▶ run](https://dipeshrayg.github.io/2026-05-01-differential-equation-visualizer/) · [⚡ codespaces](https://codespaces.new/dipeshrayg/2026-05-01-differential-equation-visualizer) |
| 2026-05-01 | [multi-agent-systems-simulator](https://github.com/dipeshrayg/2026-05-01-multi-agent-systems-simulator) | JavaScript | 10 | — | — | Emergent behavior in multi-agent systems, Swarm intelligence and flocking behavior, Dynamic obstacle avoidance | [▶ run](https://dipeshrayg.github.io/2026-05-01-multi-agent-systems-simulator/) · [⚡ codespaces](https://codespaces.new/dipeshrayg/2026-05-01-multi-agent-systems-simulator) |
| 2026-04-30 | [cellular-automata-pattern-generator](https://github.com/dipeshrayg/2026-04-30-cellular-automata-pattern-generator) | JavaScript | 9 | — | — | Cellular automata theory, Rule-based simulation, Dynamic visualization | [▶ run](https://dipeshrayg.github.io/2026-04-30-cellular-automata-pattern-generator/) · [⚡ codespaces](https://codespaces.new/dipeshrayg/2026-04-30-cellular-automata-pattern-generator) |
| 2026-04-29 | [genetic-algorithm-art-optimizer](https://github.com/dipeshrayg/2026-04-29-genetic-algorithm-art-optimizer) | JavaScript | 8 | — | — | Genetic algorithms, Crossover and mutation operations, Fitness function customization | [▶ run](https://dipeshrayg.github.io/2026-04-29-genetic-algorithm-art-optimizer/) · [⚡ codespaces](https://codespaces.new/dipeshrayg/2026-04-29-genetic-algorithm-art-optimizer) |
| 2026-04-28 | [dynamic-physics-simulator](https://github.com/dipeshrayg/2026-04-28-dynamic-physics-simulator) | JavaScript | 7 | — | — | Physics simulation, Collision detection, Elastic collisions | [▶ run](https://dipeshrayg.github.io/2026-04-28-dynamic-physics-simulator/) · [⚡ codespaces](https://codespaces.new/dipeshrayg/2026-04-28-dynamic-physics-simulator) |
| 2026-04-28 | [maze-solver-using-a-star](https://github.com/dipeshrayg/2026-04-28-maze-solver-using-a-star) | Python | 5 | — | — | A* search algorithm, heuristic optimization, graph traversal | [⚡ codespaces](https://codespaces.new/dipeshrayg/2026-04-28-maze-solver-using-a-star) |
| 2026-04-28 | [basic-neural-net-trainer](https://github.com/dipeshrayg/2026-04-28-basic-neural-net-trainer) | Python | 3 | — | — | neural networks, gradient descent, classification | [⚡ codespaces](https://codespaces.new/dipeshrayg/2026-04-28-basic-neural-net-trainer) |

---

*Generated automatically by `brain.py`. All projects are educational/diagnostic
and TOS-compliant. Last updated 2026-05-01.*
