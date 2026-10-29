-- Synapse records (docs/TEAM_PLAN.md §2.1). Files (bundles, run folders) live in Nebius Object Storage.
-- The backend connects as the database owner (bypasses RLS). Row-level security is on for every table so the
-- public anon key exposes nothing: signed-in users may read only their own rows (and the public demo
-- specialists, user_id null) through Supabase's API; nobody may write through it; api_keys is never readable.

create table public.specialists (
  specialist_id text primary key,
  user_id       uuid references auth.users (id) on delete cascade,      -- null = public demo specialist
  display_name  text not null,
  monogram      text not null,
  color         text not null,
  task_id       text not null,
  api_route     text not null,
  created_at    timestamptz not null default now()
);
create index specialists_user on public.specialists (user_id);

create table public.versions (
  specialist_id  text not null references public.specialists on delete cascade,
  version        integer not null check (version > 0),
  run_id         text not null,
  sealed_metrics jsonb not null default '{}',
  gate_result    text not null check (gate_result in ('deployed', 'rejected', 'rolled_back')),
  reason         text not null default '',
  artifact_uri   text not null,
  candidate      text,
  live           boolean not null default false,
  created_at     timestamptz not null default now(),
  primary key (specialist_id, version)
);
create unique index versions_one_live on public.versions (specialist_id) where live;

-- Per-specialist API keys: only the HMAC hash (API_KEY_PEPPER) is stored. user_id = who created the key; on a
-- demo specialist every signed-in user gets their own key, so regenerating never revokes anyone else's.
create table public.api_keys (
  key_id        text primary key,
  specialist_id text not null references public.specialists on delete cascade,
  user_id       uuid references auth.users (id) on delete cascade,
  hash          text not null unique,
  created_at    timestamptz not null default now(),
  revoked_at    timestamptz
);
create index api_keys_specialist on public.api_keys (specialist_id) where revoked_at is null;

-- Builds: the sidebar list and (step 3) the queue, claimed with FOR UPDATE SKIP LOCKED.
create table public.builds (
  run_id        text primary key,
  user_id       uuid references auth.users (id) on delete cascade,
  kind          text not null default 'build' check (kind in ('build', 'improve')),
  task_id       text not null,
  task_name     text not null,
  task_card     jsonb,
  options       jsonb not null default '{}',
  status        text not null default 'queued'
                check (status in ('queued', 'running', 'done', 'failed', 'cancelled')),
  stage         text,
  round         integer,
  n_rounds      integer,
  spend_usd     numeric(12, 6) not null default 0,
  budget_usd    numeric(12, 6),
  message       text not null default '',
  specialist_id text,
  version       integer,
  deployed      boolean,
  cancel_requested boolean not null default false,
  attempts      integer not null default 0,
  worker_id     text,
  heartbeat_at  timestamptz,
  created_at    timestamptz not null default now(),
  started_at    timestamptz,
  finished_at   timestamptz,
  updated_at    timestamptz not null default now()
);
create index builds_user on public.builds (user_id, created_at desc);
create index builds_queued on public.builds (created_at) where status = 'queued';

-- Event stream of a build (same JSON as events.jsonl); seq is the 1-based line number, so ?after=n is seq > n.
create table public.build_events (
  run_id text not null references public.builds on delete cascade,
  seq    integer not null,
  event  jsonb not null,
  primary key (run_id, seq)
);

alter table public.specialists  enable row level security;
alter table public.versions     enable row level security;
alter table public.api_keys     enable row level security;
alter table public.builds       enable row level security;
alter table public.build_events enable row level security;

create policy "read own and demo specialists" on public.specialists for select to authenticated
  using (user_id is null or user_id = (select auth.uid()));
create policy "read versions of visible specialists" on public.versions for select to authenticated
  using (exists (select 1 from public.specialists s where s.specialist_id = versions.specialist_id
                 and (s.user_id is null or s.user_id = (select auth.uid()))));
create policy "read own builds" on public.builds for select to authenticated
  using (user_id = (select auth.uid()));
create policy "read events of own builds" on public.build_events for select to authenticated
  using (exists (select 1 from public.builds b where b.run_id = build_events.run_id
                 and b.user_id = (select auth.uid())));
-- api_keys: no policy, so it can't be read or written through the API at all.
