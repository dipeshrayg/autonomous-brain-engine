# engine-node — Node.js engine (parallel build)

A Node.js port of the Autonomous Brain pipeline. Built **alongside** the Python
engine, not replacing it, so the system keeps shipping during the migration.
No dependencies — uses Node's built-in `fetch` for both LLM providers and the
Supabase REST API.

## Status

| Module | Python | Node | Notes |
|--------|--------|------|-------|
| LLM client (multi-provider fallback) | `roles.py` | ✅ `src/roles.js` | GitHub Models / Groq / Google |
| Supabase sync | `supabase_sync.py` | ✅ `src/supabaseSync.js` | reviews + build logs |
| CEO / CSO review | `executive.py` | ✅ `src/executive.js` | runnable: `npm run ceo` / `npm run cso` |
| Architect conference | `pipeline.py` | ⏳ | next |
| Implement / quality loop | `brain.py` + `pipeline.py` | ⏳ | |
| Verifier (Playwright) | `verifier.py` | ⏳ | |
| Publish (GitHub repo + Pages) | `brain.py` | ⏳ | |

## Cutover plan

1. **Parallel, low-risk first** (done): port the self-contained executive review.
   Runs on `workflow_dispatch` only — does not replace the Python cron.
2. Port the architect conference and validate plans match the Python validator.
3. Port implement + quality loop + verifier; run Node and Python on the same
   memory and diff the outputs until they agree.
4. Port publish; run a full Node build end-to-end behind a flag.
5. **Flip**: switch the daily-build workflow to the Node entry, keep Python as a
   one-command fallback.

## Run locally

```bash
cd engine-node
npm run check          # syntax check, no install needed
GITHUB_TOKEN=... GROQ_API_KEY=... GOOGLE_AI_KEY=... \
SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
node src/index.js ceo  # runs from the directory holding memory_log.json
```
