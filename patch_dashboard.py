"""One-shot patch: replace the stale readme block in dashboard.py."""
with open('dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Locate the readme = ( ... ) block by finding its start and end markers
START = '    readme = (\n'
END = '    README_PATH.write_text(readme, encoding="utf-8")'

si = content.find(START)
ei = content.find(END)
assert si != -1, "start marker not found"
assert ei != -1, "end marker not found"

# Also add the refused_count + type_summary locals just before readme = (
LOCALS_MARKER = '    readme = ('
LOCALS_INJECT = '''\
    refused_count = len(memory.get("failed_builds", []))
    type_counts: dict[str, int] = {}
    for p in projects:
        pt = p.get("project_type", "web_interactive")
        type_counts[pt] = type_counts.get(pt, 0) + 1
    type_summary = ", ".join(
        f"{pt} ({n})" for pt, n in sorted(type_counts.items(), key=lambda x: -x[1])
    ) or "-"

    readme = (
'''

NEW_BODY = (
    '        f"# Autonomous Brain\\n\\n"\n'
    '        f"A zero-cost, fully autonomous multi-agent AI pipeline that continuously conceives,\\n"\n'
    '        f"architects, implements, quality-assures, and publishes novel software projects\\n"\n'
    '        f"without any human intervention.\\n\\n"\n'
    '        f"**13 AI agents. 3 providers. 0 infrastructure cost. 0 human interventions.**\\n\\n"\n'
    '        f"**Live dashboard:** https://{owner}.github.io/{repo}/\\n\\n"\n'
    '        f"Every project below is a separate public repository with a live deployed URL.\\n\\n"\n'
    '        f"## Stats\\n\\n"\n'
    '        f"| Metric | Value |\\n"\n'
    '        f"|--------|-------|\\n"\n'
    '        f"| Projects shipped | {total} |\\n"\n'
    '        f"| Builds auto-refused (quality gate) | {refused_count}+ |\\n"\n'
    '        f"| Peak complexity | {max((p.get(\'complexity_score\', 0) for p in projects), default=0)} (open-ended scale) |\\n"\n'
    '        f"| Average complexity | {avg:.1f} |\\n"\n'
    '        f"| Daily cadence | Up to 5/day, fully autonomous |\\n"\n'
    '        f"| Infrastructure cost | $0 |\\n"\n'
    '        f"| Human interventions | 0 |\\n"\n'
    '        f"| Latest run | {latest} |\\n\\n"\n'
    '        f"**Languages explored:** {\', \'.join(languages) if languages else \'-\'}  \\n"\n'
    '        f"**Project types shipped:** {type_summary}  \\n"\n'
    '        f"**Domains explored:** {\', \'.join(_recent_unique([p.get(\'domain\') for p in projects], 8)) or \'-\'}\\n\\n"\n'
    '        f"## Latest creations\\n\\n"\n'
    '        f"| Date | Project | Lang | Complexity | Pattern | Domain | Concepts | Run |\\n"\n'
    '        f"|------|---------|------|------------|---------|--------|----------|-----|\\n"\n'
    '        f"{table}\\n"\n'
    '        f"{ceo_block}"\n'
    '        f"\\n## The boardroom - 13 roles, 3 providers\\n\\n"\n'
    '        f"Each role uses a different model family for genuinely adversarial perspectives.\\n"\n'
    '        f"All providers are free-tier. Missing API keys are silently skipped.\\n\\n"\n'
    '        f"| Role | Model | Provider | Purpose |\\n"\n'
    '        f"|------|-------|----------|---------|\\n"\n'
    '        f"| CEO | `gpt-4o` | GitHub Models | Visionary strategy, domain pivots - runs 4x/day |\\n"\n'
    '        f"| CSO | `llama-3.3-70b-versatile` | Groq | Scientific novelty, algorithmic depth - runs 2x/day |\\n"\n'
    '        f"| CTO | `gemini-2.0-flash` | Google AI Studio | Reads failure logs, patches its own source code |\\n"\n'
    '        f"| Architect A | `mixtral-8x7b-32768` | Groq | Creative planning (Mistral lens) |\\n"\n'
    '        f"| Architect B | `llama-3.3-70b-versatile` | Groq | Creative planning (Meta lens) |\\n"\n'
    '        f"| Judge | `gpt-4o` | GitHub Models | Predictability filter - rejects derivative ideas |\\n"\n'
    '        f"| Engineer | `gpt-4o` | GitHub Models | Per-file implementation with full sibling context |\\n"\n'
    '        f"| Reviewer A | `mixtral-8x7b-32768` | Groq | Code review (Mistral lens) |\\n"\n'
    '        f"| Reviewer B | `gemini-2.0-flash` | Google AI Studio | Code review (Gemini lens) |\\n"\n'
    '        f"| QA Tester | `gpt-4o` | GitHub Models | User-pathway simulation |\\n"\n'
    '        f"| QA Fixer | `gemini-2.0-flash` | Google AI Studio | Repairs dead controls |\\n"\n'
    '        f"| Polisher | `Phi-4` | GitHub Models | UX refinement |\\n"\n'
    '        f"| Fixer | `gpt-4o-mini` | GitHub Models | Iterative repair loop |\\n\\n"\n'
    '        f"## How it works\\n\\n"\n'
    '        f"```\\n"\n'
    '        f"STAGE 1  ARCHITECT CONFERENCE\\n"\n'
    '        f"         Architect A (Mixtral/Groq) + Architect B (Llama/Groq) propose plans in parallel\\n"\n'
    '        f"         Judge (GPT-4o) synthesises or proposes a more unpredictable plan\\n\\n"\n'
    '        f"STAGE 2  IMPLEMENT\\n"\n'
    '        f"         Engineer (GPT-4o) writes each file with full sibling context\\n\\n"\n'
    '        f"STAGE 3  QUALITY LOOP (up to 8 rounds)\\n"\n'
    '        f"         Reviewer A (Mixtral/Groq) + Reviewer B (Gemini) in parallel\\n"\n'
    '        f"         Fixer applies merged feedback + Playwright interaction test\\n\\n"\n'
    '        f"STAGE 4  QA REVIEW\\n"\n'
    '        f"         Playwright clicks every button, tests every slider\\n"\n'
    '        f"         QA Tester (GPT-4o) issues verdict: shippable / partially_usable / non_functional\\n\\n"\n'
    '        f"STAGE 5  PUBLISH\\n"\n'
    '        f"         New public GitHub repo created via API\\n"\n'
    '        f"         GitHub Pages enabled -> live URL in under 60 minutes from cold start\\n\\n"\n'
    '        f"STAGE 6  SELF-IMPROVE\\n"\n'
    '        f"         CTO (Gemini) reads last 30 failure logs, proposes a surgical source patch\\n"\n'
    '        f"         Validates Python syntax, commits - next build runs improved code\\n"\n'
    '        f"```\\n\\n"\n'
    '        f"## Project types (10 available)\\n\\n"\n'
    '        f"| Type | Description |\\n"\n'
    '        f"|------|-------------|\\n"\n'
    '        f"| `web_interactive` | HTML+JS+Canvas browser demos |\\n"\n'
    '        f"| `game_web` | Browser games with rules, state, win condition |\\n"\n'
    '        f"| `python_tool` | Standalone Python programs |\\n"\n'
    '        f"| `generative_art` | Visual output - canvas or SVG |\\n"\n'
    '        f"| `document` | Markdown research articles, styled as web pages |\\n"\n'
    '        f"| `web_3d` | Three.js / WebGL 3D scenes |\\n"\n'
    '        f"| `shader_art` | GLSL fragment shaders, pure WebGL |\\n"\n'
    '        f"| `data_viz` | Python matplotlib/plotly with interactive SVG embed |\\n"\n'
    '        f"| `typescript_app` | TypeScript via esm.sh CDN, no build step |\\n"\n'
    '        f"| `cli_tool` | Rust or Go CLI + Codespaces devcontainer |\\n\\n"\n'
    '        f"---\\n\\n"\n'
    '        f"*Engine: [autonomous-brain-engine](https://github.com/{owner}/autonomous-brain-engine) - "\n'
    '        f"ORCID: [0009-0001-9970-0220](https://orcid.org/0009-0001-9970-0220) - "\n'
    '        f"Built by Dipesh Ray - Infrastructure cost: $0 - Last updated {latest}.*\\n"\n'
    '    )\n'
)

new_content = content[:si] + LOCALS_INJECT + NEW_BODY + '\n' + content[ei:]

with open('dashboard.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"Patched: removed chars {si}-{ei}, inserted new readme block")
print(f"Old length: {len(content)}, New length: {len(new_content)}")

# Quick syntax check
import ast
ast.parse(new_content)
print("Syntax OK")
