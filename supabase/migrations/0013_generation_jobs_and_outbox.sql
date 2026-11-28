-- PWA Studio: durable generation job records + transactional dispatch outbox.
-- REVIEW ONLY: do not apply to production from this feature branch.
-- No provider, worker, API endpoint, or billing flow is enabled by this migration.

create extension if not exists pgcrypto;

create table if not exists public.generation_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key text not null check (char_length(idempotency_key) between 8 and 160),
  request_fingerprint text not null check (request_fingerprint ~ '^[a-f0-9]{64}$'),
  job_type text not null check (job_type in ('image', 'video')),
  status text not null default 'queued'
    check (status in ('queued','processing','retry_wait','cancel_requested','reconciliation_required','succeeded','failed','cancelled')),
  -- Store only the minimum validated request required by a worker.
  -- Never put credentials, signed URLs, or client-supplied owner IDs here.
  request_payload jsonb not null default '{}'::jsonb
    check (jsonb_typeof(request_payload) = 'object'),
  provider text,
  model text,
  -- Evidence about whether the external provider accepted this attempt.
  -- Unknown is the safe default: an expired worker must not blindly resubmit.
  provider_submission_outcome text not null default 'unknown'
    check (provider_submission_outcome in ('unknown','definitely_not_submitted','definitely_rejected','accepted')),
  attempt_count integer not null default 0 check (attempt_count >= 0 and attempt_count <= 5),
  max_attempts integer not null default 3 check (max_attempts between 1 and 5),
  worker_id text,
  lease_token uuid,
  lease_expires_at timestamptz,
  next_attempt_at timestamptz,
  cancel_requested_at timestamptz,
  result_asset_id uuid,
  safe_error_code text check (safe_error_code is null or char_length(safe_error_code) <= 80),
  estimated_cost_usd numeric(20,10) check (estimated_cost_usd is null or (estimated_cost_usd >= 0 and estimated_cost_usd <> 'NaN'::numeric and estimated_cost_usd <> 'Infinity'::numeric and estimated_cost_usd <> '-Infinity'::numeric)),
  actual_cost_usd numeric(20,10) check (actual_cost_usd is null or (actual_cost_usd >= 0 and actual_cost_usd <> 'NaN'::numeric and actual_cost_usd <> 'Infinity'::numeric and actual_cost_usd <> '-Infinity'::numeric)),
  reserved_credits integer check (reserved_credits is null or reserved_credits >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  constraint generation_jobs_owner_idempotency_unique unique (owner_id, idempotency_key),
  constraint generation_jobs_lease_consistency check (
    (status in ('processing','cancel_requested') and lease_token is not null and lease_expires_at is not null)
    or
    (status not in ('processing','cancel_requested') and lease_token is null and lease_expires_at is null)
  ),
  constraint generation_jobs_terminal_time check (
    (status in ('succeeded','failed','cancelled') and completed_at is not null)
    or
    (status not in ('succeeded','failed','cancelled') and completed_at is null)
  ),
  constraint generation_jobs_attempts check (attempt_count <= max_attempts)
);

create index if not exists generation_jobs_owner_created_idx
  on public.generation_jobs(owner_id, created_at desc);
create index if not exists generation_jobs_claim_idx
  on public.generation_jobs(status, next_attempt_at, created_at)
  where status in ('queued','retry_wait');
create index if not exists generation_jobs_expired_lease_idx
  on public.generation_jobs(lease_expires_at)
  where status in ('processing','cancel_requested');

-- Transactional outbox: enqueue a dispatch record in the same DB transaction
-- that creates the generation job. This prevents a committed job being lost
-- between DB commit and publishing to an external queue.
create table if not exists public.generation_job_outbox (
  id bigint generated always as identity primary key,
  job_id uuid not null references public.generation_jobs(id) on delete cascade,
  event_type text not null check (event_type in ('job_queued','job_retry_ready','job_cancel_requested')),
  available_at timestamptz not null default now(),
  claimed_at timestamptz,
  claim_token uuid,
  delivered_at timestamptz,
  delivery_attempts integer not null default 0 check (delivery_attempts >= 0),
  created_at timestamptz not null default now(),
  constraint generation_job_outbox_claim_consistency check (
    (claimed_at is null and claim_token is null) or
    (claimed_at is not null and claim_token is not null)
  )
);
create index if not exists generation_job_outbox_pending_idx
  on public.generation_job_outbox(available_at, id)
  where delivered_at is null;

alter table public.generation_jobs enable row level security;
alter table public.generation_job_outbox enable row level security;

-- Browser clients may only read their own job status. No client-side writes.
revoke all on public.generation_jobs from anon, authenticated;
grant select on public.generation_jobs to authenticated;
drop policy if exists generation_jobs_read_own on public.generation_jobs;
create policy generation_jobs_read_own on public.generation_jobs
  for select to authenticated using (owner_id = auth.uid());

-- Outbox is strictly backend-only; no policies for anon/authenticated.
revoke all on public.generation_job_outbox from anon, authenticated;

-- Backend uses service_role after validating the user's Supabase JWT and
-- deriving owner_id from the verified token. Never expose service_role to clients.
grant select, insert, update, delete on public.generation_jobs to service_role;
grant select, insert, update, delete on public.generation_job_outbox to service_role;
grant usage, select on sequence public.generation_job_outbox_id_seq to service_role;

comment on table public.generation_jobs is
  'Private generation job state. Clients can read only their own rows; all writes are backend-managed.';
comment on table public.generation_job_outbox is
  'Backend-only transactional outbox for reliable generation job dispatch.';
comment on column public.generation_jobs.request_payload is
  'Minimal validated request payload. Never store credentials, signed URLs, or client-supplied ownership fields.';
comment on column public.generation_jobs.lease_token is
  'Per-attempt fencing token. Worker writes must match both job id and lease token to prevent stale workers overwriting newer attempts.';
