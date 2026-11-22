-- PWA Studio: durable generation job and transactional outbox foundation.
-- This migration creates schema only. No worker/Redis/provider is enabled by it.
-- Apply manually only after reviewing the target database and running a backup.

create extension if not exists pgcrypto;

-- Composite parent key allows the database to enforce that a job's project
-- belongs to the same user who owns the job.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.projects'::regclass
      and conname = 'projects_id_owner_id_key'
  ) then
    alter table public.projects
      add constraint projects_id_owner_id_key unique (id, owner_id);
  end if;
end;
$$;

create table if not exists public.generation_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid null,
  job_type text not null check (job_type in (
    'image_generation', 'video_generation', 'audio_generation',
    'speech_generation', 'ai_processing', 'media_export'
  )),
  provider text not null,
  model text not null,
  status text not null default 'queued' check (status in (
    'queued', 'running', 'retry_wait', 'succeeded', 'failed',
    'cancel_requested', 'cancelled', 'expired'
  )),
  idempotency_key text not null check (char_length(idempotency_key) between 8 and 200),
  request_hash text not null check (char_length(request_hash) between 32 and 128),
  request_snapshot jsonb not null default '{}'::jsonb,
  pricing_snapshot jsonb not null default '{}'::jsonb,
  result_storage_path text,
  provider_job_id text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  available_at timestamptz not null default now(),
  lease_owner text,
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  last_error_code text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  constraint generation_jobs_user_idempotency_key unique (user_id, idempotency_key),
  constraint generation_jobs_project_owner_fkey
    foreign key (project_id, user_id)
    references public.projects (id, owner_id)
    on delete set null (project_id),
  constraint generation_jobs_lease_consistency check (
    (status = 'running' and lease_owner is not null and lease_expires_at is not null)
    or status <> 'running'
  ),
  constraint generation_jobs_terminal_timestamp check (
    (status in ('succeeded', 'failed', 'cancelled', 'expired') and completed_at is not null)
    or (status not in ('succeeded', 'failed', 'cancelled', 'expired'))
  )
);

create index if not exists generation_jobs_queue_idx
  on public.generation_jobs(status, available_at, created_at)
  where status in ('queued', 'retry_wait');

create index if not exists generation_jobs_expired_lease_idx
  on public.generation_jobs(lease_expires_at)
  where status = 'running';

create index if not exists generation_jobs_user_history_idx
  on public.generation_jobs(user_id, created_at desc);

create index if not exists generation_jobs_project_history_idx
  on public.generation_jobs(project_id, created_at desc)
  where project_id is not null;

alter table public.generation_jobs enable row level security;
revoke all on public.generation_jobs from anon, authenticated;
grant select on public.generation_jobs to authenticated;
grant all on public.generation_jobs to service_role;

drop policy if exists "Users read own generation jobs" on public.generation_jobs;
create policy "Users read own generation jobs" on public.generation_jobs
  for select to authenticated
  using (auth.uid() = user_id);

-- Transactional outbox: the API will insert the job and event in the same
-- database transaction. A dispatcher can retry delivery to Redis safely.
create table if not exists public.outbox_events (
  id bigint generated always as identity primary key,
  event_id uuid not null default gen_random_uuid() unique,
  aggregate_type text not null check (aggregate_type = 'generation_job'),
  aggregate_id uuid not null references public.generation_jobs(id) on delete cascade,
  event_type text not null check (event_type in ('generation_job.created', 'generation_job.retry')),
  payload jsonb not null default '{}'::jsonb,
  available_at timestamptz not null default now(),
  published_at timestamptz,
  delivery_attempts integer not null default 0 check (delivery_attempts >= 0),
  last_error_code text,
  created_at timestamptz not null default now()
);

create index if not exists outbox_events_pending_idx
  on public.outbox_events(available_at, id)
  where published_at is null;

alter table public.outbox_events enable row level security;
revoke all on public.outbox_events from anon, authenticated;
grant all on public.outbox_events to service_role;

-- No client policies are created for outbox_events. Only trusted backend
-- service-role operations may read or mutate delivery state.
