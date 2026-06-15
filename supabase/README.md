# Supabase — System of Record

This project's logs, projects, reviews, and runtime state live in a Supabase
(Postgres) database with **Row Level Security enforced on every table**.

## Access model

| Data | Who can read | How |
|------|--------------|-----|
| `projects` (shipped deliverables) | **Public** | anon key + RLS `select` policy |
| `taxonomy` (concepts/patterns/domains) | **Public** | anon key + RLS `select` policy |
| `public_stats` (aggregate header) | **Public** | view, `security_invoker` |
| `failed_builds` | Authenticated users only | login via Supabase Auth |
| `ceo_reviews`, `cso_reviews` | Authenticated users only | login via Supabase Auth |
| `build_logs` (every log line) | Authenticated users only | login via Supabase Auth |
| `system_state` | Authenticated users only | login via Supabase Auth |
| **All writes** | **Engine only** | `service_role` key (bypasses RLS) |

The frontend never holds the `service_role` key. The engine never ships the
`service_role` key to the browser. Writes are impossible from the public side.

## One-time setup

1. **Create a free Supabase project** at https://supabase.com → New project.
   Note the **Project URL** and, under *Project Settings → API*, the
   **anon public** key and the **service_role** key.

2. **Apply the schema.** In Supabase Studio → SQL Editor, paste and run
   [`migrations/0001_initial_schema.sql`](migrations/0001_initial_schema.sql).
   (Or, with the Supabase CLI linked: `supabase db push`.)

3. **Backfill existing data** (your current `memory_log.json`):

   ```bash
   export SUPABASE_URL="https://<ref>.supabase.co"
   export SUPABASE_SERVICE_ROLE_KEY="<service_role key>"
   python scripts/backfill_supabase.py        # add --reset to truncate+reload
   ```

4. **Add the keys as GitHub Actions secrets** (Settings → Secrets and variables
   → Actions) so the engine can write on every build:

   | Secret | Value | Used by |
   |--------|-------|---------|
   | `SUPABASE_URL` | `https://<ref>.supabase.co` | engine (write) |
   | `SUPABASE_SERVICE_ROLE_KEY` | service_role key | engine (write) — **secret** |

5. **Frontend env** (committed as build-time vars, anon key is safe to expose):

   | Var | Value |
   |-----|-------|
   | `VITE_SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `VITE_SUPABASE_ANON_KEY` | anon public key |

## Why this is board-credible

- A normalized Postgres schema with indexes, not a flat JSON blob.
- Security model you can defend in one sentence: *public showcase, auth-gated
  operations, all writes locked to a service role, RLS on every table.*
- Fully online and free (Supabase free tier), preserving the zero-cost thesis.
