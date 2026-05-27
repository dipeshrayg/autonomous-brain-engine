"""Rewrite render_dashboard in dashboard.py cleanly."""
with open('dashboard.py', 'r', encoding='utf-8') as f:
    src = f.read()

# Replace just the rows.append block and table fallback
OLD = (
    "        plan_model = (p.get(\"model_attribution\") or {}).get(\"plan_judge\", \"—\")\n"
    "        rows.append(\n"
    "            f\"| {p.get('date')} | [{p.get('name')}]({p.get('repo_url')}) \"\n"
    "            f\"| {p.get('language')} | {p.get('complexity_score')} | {pattern} | {domain} \"\n"
    "            f\"| {plan_model} | {concepts} | {run_cell} |\"\n"
    "        )\n"
    "    table = \"\\n\".join(rows) if rows else \"| — | _no projects yet_ | — | — | — | — | — | — | — |\""
)

NEW = (
    "        rows.append(\n"
    "            f\"| {p.get('date')} | [{p.get('name')}]({p.get('repo_url')}) \"\n"
    "            f\"| {p.get('language')} | {p.get('complexity_score')} | {pattern} | {domain} \"\n"
    "            f\"| {concepts} | {run_cell} |\"\n"
    "        )\n"
    "    table = \"\\n\".join(rows) if rows else \"| - | _no projects yet_ | - | - | - | - | - | - |\""
)

if OLD in src:
    src = src.replace(OLD, NEW)
    with open('dashboard.py', 'w', encoding='utf-8') as f:
        f.write(src)
    import ast
    ast.parse(src)
    print("OK - patched and syntax valid")
else:
    print("BLOCK NOT FOUND")
    # Show what's around plan_model
    idx = src.find("plan_model")
    print(repr(src[idx-10:idx+400]))
