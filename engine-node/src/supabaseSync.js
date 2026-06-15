/**
 * supabaseSync.js — best-effort mirror of engine state into Supabase (Node port).
 * Never throws; if unconfigured/unreachable, logs a warning and returns false.
 * Writes use the SERVICE_ROLE key (bypasses RLS), from env / GitHub Secrets.
 */

const URL = (process.env.SUPABASE_URL || '').replace(/\/$/, '')
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || ''

export const enabled = () => Boolean(URL && KEY)

function headers(extra = {}) {
  return { apikey: KEY, Authorization: `Bearer ${KEY}`, 'Content-Type': 'application/json', ...extra }
}

async function post(table, row, onConflict = null) {
  if (!enabled()) { console.log(`Supabase not configured; skipping ${table} sync.`); return false }
  let url = `${URL}/rest/v1/${table}`
  if (onConflict) url += `?on_conflict=${onConflict}`
  const prefer = 'return=minimal' + (onConflict ? ',resolution=merge-duplicates' : '')
  try {
    const r = await fetch(url, { method: 'POST', headers: headers({ Prefer: prefer }), body: JSON.stringify([row]) })
    if (!r.ok) { console.warn(`Supabase ${table} sync failed [${r.status}]: ${(await r.text()).slice(0, 200)}`); return false }
    console.log(`Supabase: synced 1 row -> ${table}`)
    return true
  } catch (e) {
    console.warn(`Supabase ${table} sync error: ${e.message}`)
    return false
  }
}

export async function syncReview(table, record) {
  const cols = ['verdict', 'summary', 'concerns', 'directives', 'praise', 'model', 'reviewed_project_count']
  const row = {}
  for (const c of cols) if (record[c] !== undefined) row[c] = record[c]
  row.verdict = row.verdict || 'acceptable'
  row.issued_at = record.issued_at
  return post(table, row)
}

export async function logEvent(level, stage, message, { projectSlug = null, runId = null, metadata = {} } = {}) {
  return post('build_logs', {
    level, stage, message: String(message).slice(0, 2000),
    project_slug: projectSlug, run_id: runId || process.env.GITHUB_RUN_ID, metadata,
  })
}
