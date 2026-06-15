-- ============================================================================
-- Autonomous Brain — Supabase (Postgres) schema
-- ============================================================================
-- Design goals:
--   * Real system of record for every shipped project, refused build, executive
--     review, and build-time log line (replaces the flat memory_log.json file).
--   * RLS enforced on EVERY table. Public can see the project showcase; all
--     operational data (failure logs, reviews, raw build logs, system state) is
--     readable only by authenticated users.
--   * The autonomous engine writes using the Supabase SERVICE_ROLE key, which
--     bypasses RLS. The frontend uses the ANON key, which is bound by RLS.
--
-- Apply with:  supabase db push      (CLI)
--          or: paste into Supabase Studio → SQL Editor → Run
-- ============================================================================

create extension if not exists "pgcrypto";

-- ----------------------------------------------------------------------------
-- projects  —  shipped deliverables  (PUBLIC read)
-- ----------------------------------------------------------------------------
create table if not exists public.projects (
  id                       uuid primary key default gen_random_uuid(),
  slug                     text unique not null,        -- 2026-06-15-ai-dream-generator
  name                     text not null,
  date                     date not null,
  completed_at             timestamptz not null,
  project_type             text not null,
  language                 text,
  complexity_score         integer not null default 0,
  pattern                  text,
  domain                   text,
  description              text,
  long_description         text,
  advancement_axis         text,
  visual_identity          text,
  safety_notes             text,
  repo_url                 text,
  pages_url                text,
  tech_stack               jsonb not null default '[]'::jsonb,
  concepts_demonstrated    jsonb not null default '[]'::jsonb,
  novel_concepts           jsonb not null default '[]'::jsonb,
  file_count               integer,
  loc                      integer,
  quality_cycles_used      integer,
  qa_verdict               text,
  qa_review                jsonb,
  final_verify_metrics     jsonb,
  model_attribution        jsonb,
  ceo_directives_followed  jsonb not null default '[]'::jsonb,
  created_at               timestamptz not null default now()
);
create index if not exists projects_completed_at_idx on public.projects (completed_at desc);
create index if not exists projects_type_idx          on public.projects (project_type);
create index if not exists projects_complexity_idx    on public.projects (complexity_score);

-- ----------------------------------------------------------------------------
-- failed_builds  —  refused attempts  (AUTH read)
-- ----------------------------------------------------------------------------
create table if not exists public.failed_builds (
  id                       uuid primary key default gen_random_uuid(),
  plan_name                text,
  project_type             text,
  plan_language            text,
  plan_complexity          integer,
  plan_pattern             text,
  plan_domain              text,
  plan_files_count         integer,
  refusal_stage            text,
  refusal_reason           text,
  qa_verdict               text,
  qa_dead_controls         jsonb not null default '[]'::jsonb,
  qa_missing_features      jsonb not null default '[]'::jsonb,
  final_interaction        jsonb,
  final_interactive_count  integer,
  attempted_at             timestamptz not null,
  created_at               timestamptz not null default now()
);
create index if not exists failed_attempted_at_idx on public.failed_builds (attempted_at desc);
create index if not exists failed_type_idx         on public.failed_builds (project_type);

-- ----------------------------------------------------------------------------
-- ceo_reviews / cso_reviews  —  executive watchdog verdicts  (AUTH read)
-- ----------------------------------------------------------------------------
create table if not exists public.ceo_reviews (
  id                       uuid primary key default gen_random_uuid(),
  verdict                  text not null,
  summary                  text,
  concerns                 jsonb not null default '[]'::jsonb,
  directives               jsonb not null default '[]'::jsonb,
  praise                   jsonb not null default '[]'::jsonb,
  model                    text,
  reviewed_project_count   integer,
  issued_at                timestamptz not null,
  created_at               timestamptz not null default now()
);
create index if not exists ceo_issued_at_idx on public.ceo_reviews (issued_at desc);

create table if not exists public.cso_reviews (
  id                       uuid primary key default gen_random_uuid(),
  verdict                  text not null,
  summary                  text,
  concerns                 jsonb not null default '[]'::jsonb,
  directives               jsonb not null default '[]'::jsonb,
  praise                   jsonb not null default '[]'::jsonb,
  model                    text,
  reviewed_project_count   integer,
  issued_at                timestamptz not null,
  created_at               timestamptz not null default now()
);
create index if not exists cso_issued_at_idx on public.cso_reviews (issued_at desc);

-- ----------------------------------------------------------------------------
-- build_logs  —  append-only event stream ("record every log")  (AUTH read)
-- ----------------------------------------------------------------------------
create table if not exists public.build_logs (
  id            bigint generated always as identity primary key,
  run_id        text,                                   -- GitHub Actions run id
  project_slug  text,
  level         text not null default 'info',           -- info | warning | error
  stage         text,                                   -- architect | implement | qa | publish | ...
  message       text not null,
  metadata      jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);
create index if not exists logs_created_at_idx on public.build_logs (created_at desc);
create index if not exists logs_run_id_idx     on public.build_logs (run_id);
create index if not exists logs_level_idx      on public.build_logs (level);

-- ----------------------------------------------------------------------------
-- taxonomy  —  concepts / patterns / domains explored  (PUBLIC read)
-- ----------------------------------------------------------------------------
create table if not exists public.taxonomy (
  id          uuid primary key default gen_random_uuid(),
  kind        text not null check (kind in ('concept','pattern','domain')),
  value       text not null,
  first_seen  timestamptz not null default now(),
  unique (kind, value)
);

-- ----------------------------------------------------------------------------
-- system_state  —  singleton runtime flags  (AUTH read)
-- ----------------------------------------------------------------------------
create table if not exists public.system_state (
  id                    integer primary key default 1 check (id = 1),
  expansion_mode        boolean not null default false,
  expansion_mode_since  timestamptz,
  updated_at            timestamptz not null default now()
);
insert into public.system_state (id) values (1) on conflict (id) do nothing;

-- ============================================================================
-- Row Level Security
-- ============================================================================
-- Enable RLS everywhere. With RLS on and no permissive policy for a role, that
-- role is denied. The SERVICE_ROLE key used by the engine BYPASSES RLS, so the
-- pipeline can write freely; anon/authenticated are bound by the policies below.
-- ----------------------------------------------------------------------------
alter table public.projects      enable row level security;
alter table public.failed_builds enable row level security;
alter table public.ceo_reviews   enable row level security;
alter table public.cso_reviews   enable row level security;
alter table public.build_logs    enable row level security;
alter table public.taxonomy      enable row level security;
alter table public.system_state  enable row level security;

-- PUBLIC read: the showcase (projects + taxonomy) is world-readable.
drop policy if exists "projects_public_read" on public.projects;
create policy "projects_public_read" on public.projects
  for select to anon, authenticated using (true);

drop policy if exists "taxonomy_public_read" on public.taxonomy;
create policy "taxonomy_public_read" on public.taxonomy
  for select to anon, authenticated using (true);

-- AUTH-only read: operational data requires a logged-in Supabase user.
drop policy if exists "failed_auth_read" on public.failed_builds;
create policy "failed_auth_read" on public.failed_builds
  for select to authenticated using (true);

drop policy if exists "ceo_auth_read" on public.ceo_reviews;
create policy "ceo_auth_read" on public.ceo_reviews
  for select to authenticated using (true);

drop policy if exists "cso_auth_read" on public.cso_reviews;
create policy "cso_auth_read" on public.cso_reviews
  for select to authenticated using (true);

drop policy if exists "logs_auth_read" on public.build_logs;
create policy "logs_auth_read" on public.build_logs
  for select to authenticated using (true);

drop policy if exists "state_auth_read" on public.system_state;
create policy "state_auth_read" on public.system_state
  for select to authenticated using (true);

-- NOTE: no INSERT/UPDATE/DELETE policies are defined for anon/authenticated,
-- so all writes from the frontend are denied. Only the engine's service_role
-- key (which bypasses RLS) may write. This is the security model you asked for.

-- ============================================================================
-- public_stats  —  safe aggregate view for the public showcase header
-- ============================================================================
create or replace view public.public_stats
with (security_invoker = on) as
  select
    (select count(*)                       from public.projects)            as total_projects,
    (select count(distinct project_type)   from public.projects)            as project_types,
    (select coalesce(max(complexity_score),0) from public.projects)         as peak_complexity,
    (select count(*) from public.taxonomy where kind = 'concept')           as concepts_explored,
    (select count(*) from public.taxonomy where kind = 'domain')            as domains_explored;

grant select on public.public_stats to anon, authenticated;
