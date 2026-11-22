-- PWA Studio: durable provider-operation journal for ambiguous submissions.
-- Schema/RPC primitives only. No provider calls, worker activation or production migration.
-- Apply after 0016_harden_generation_job_idempotency.sql.

create table if not exists public.generation_provider_operations (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null unique references public.generation_jobs(id) on delete cascade,
  provider text not null check (length(btrim(provider)) between 1 and 100),
  idempotency_key text not null check (length(idempotency_key) between 8 and 200),
  state text not null default 'submitting' check (state in (
    'submitting', 'accepted', 'unknown', 'provider_failed', 'result_received'
  )),
  provider_request_id text,
  last_error_code text,
  first_submitted_at timestamptz not null default now(),
  last_checked_at timestamptz,
  accepted_at timestamptz,
  result_received_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint generation_provider_operations_job_provider_key
    unique (job_id, provider, idempotency_key),
  constraint generation_provider_operations_request_id_length
    check (provider_request_id is null or length(provider_request_id) between 1 and 500),
  constraint generation_provider_operations_error_code
    check (last_error_code is null or last_error_code ~ '^[a-z0-9_]{1,80}$')
);

create index if not exists generation_provider_operations_state_idx
  on public.generation_provider_operations(state, updated_at);

alter table public.generation_provider_operations enable row level security;
revoke all on public.generation_provider_operations from anon, authenticated;
grant all on public.generation_provider_operations to service_role;

create or replace function public.begin_generation_provider_operation(
  p_job_id uuid,
  p_worker_id text,
  p_provider text,
  p_idempotency_key text
)
returns table (operation_id uuid, operation_state text, provider_request_id text, created boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_operation public.generation_provider_operations%rowtype;
  v_created boolean := false;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_provider is null or length(btrim(p_provider)) not between 1 and 100
     or p_idempotency_key is null or length(p_idempotency_key) not between 8 and 200 then
    raise exception 'Invalid provider operation metadata' using errcode = '22023';
  end if;

  select * into v_job
    from public.generation_jobs
   where id = p_job_id
   for update;

  if not found or v_job.status <> 'running'
     or v_job.lease_owner <> btrim(p_worker_id)
     or v_job.lease_expires_at <= now() then
    raise exception 'Active generation job lease required' using errcode = '42501';
  end if;

  if v_job.provider <> btrim(p_provider)
     or v_job.idempotency_key <> p_idempotency_key then
    raise exception 'Provider operation does not match generation job' using errcode = '22023';
  end if;

  insert into public.generation_provider_operations(job_id, provider, idempotency_key)
  values (p_job_id, btrim(p_provider), p_idempotency_key)
  on conflict (job_id) do nothing
  returning * into v_operation;

  if found then
    v_created := true;
  else
    select * into v_operation
      from public.generation_provider_operations
     where job_id = p_job_id
     for update;
    if v_operation.provider <> btrim(p_provider)
       or v_operation.idempotency_key <> p_idempotency_key then
      raise exception 'Existing provider operation identity mismatch' using errcode = '23505';
    end if;
  end if;

  return query select v_operation.id, v_operation.state,
                      v_operation.provider_request_id, v_created;
end;
$$;

create or replace function public.mark_generation_provider_operation_accepted(
  p_job_id uuid,
  p_worker_id text,
  p_provider_request_id text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare v_updated integer;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_provider_request_id is null or length(p_provider_request_id) not between 1 and 500 then
    raise exception 'Invalid provider acceptance metadata' using errcode = '22023';
  end if;

  update public.generation_provider_operations as op
     set state = 'accepted',
         provider_request_id = p_provider_request_id,
         accepted_at = coalesce(accepted_at, now()),
         last_checked_at = now(),
         updated_at = now()
    from public.generation_jobs as job
   where op.job_id = p_job_id
     and job.id = op.job_id
     and job.status = 'running'
     and job.lease_owner = btrim(p_worker_id)
     and job.lease_expires_at > now()
     and op.state in ('submitting', 'unknown', 'accepted')
     and (op.provider_request_id is null or op.provider_request_id = p_provider_request_id);

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

create or replace function public.mark_generation_provider_operation_unknown(
  p_job_id uuid,
  p_worker_id text,
  p_error_code text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare v_updated integer;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_error_code is null or p_error_code !~ '^[a-z0-9_]{1,80}$' then
    raise exception 'Invalid ambiguous provider operation metadata' using errcode = '22023';
  end if;

  update public.generation_provider_operations as op
     set state = 'unknown',
         last_error_code = p_error_code,
         last_checked_at = now(),
         updated_at = now()
    from public.generation_jobs as job
   where op.job_id = p_job_id
     and job.id = op.job_id
     and job.status = 'running'
     and job.lease_owner = btrim(p_worker_id)
     and job.lease_expires_at > now()
     and op.state in ('submitting', 'accepted', 'unknown');

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

create or replace function public.mark_generation_provider_operation_failed(
  p_job_id uuid,
  p_worker_id text,
  p_error_code text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare v_updated integer;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_error_code is null or p_error_code !~ '^[a-z0-9_]{1,80}$' then
    raise exception 'Invalid provider failure metadata' using errcode = '22023';
  end if;

  update public.generation_provider_operations as op
     set state = 'provider_failed',
         last_error_code = p_error_code,
         last_checked_at = now(),
         updated_at = now()
    from public.generation_jobs as job
   where op.job_id = p_job_id
     and job.id = op.job_id
     and job.status = 'running'
     and job.lease_owner = btrim(p_worker_id)
     and job.lease_expires_at > now()
     and op.state in ('submitting', 'accepted', 'unknown', 'provider_failed');

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

revoke all on function public.begin_generation_provider_operation(uuid, text, text, text) from public, anon, authenticated;
revoke all on function public.mark_generation_provider_operation_accepted(uuid, text, text) from public, anon, authenticated;
revoke all on function public.mark_generation_provider_operation_unknown(uuid, text, text) from public, anon, authenticated;
revoke all on function public.mark_generation_provider_operation_failed(uuid, text, text) from public, anon, authenticated;

grant execute on function public.begin_generation_provider_operation(uuid, text, text, text) to service_role;
grant execute on function public.mark_generation_provider_operation_accepted(uuid, text, text) to service_role;
grant execute on function public.mark_generation_provider_operation_unknown(uuid, text, text) to service_role;
grant execute on function public.mark_generation_provider_operation_failed(uuid, text, text) to service_role;

comment on table public.generation_provider_operations is
  'Durable journal for one external provider operation per generation job; unknown means never blindly resubmit without provider reconciliation.';


-- Persist the fact that the provider returned a result before storage upload starts.
-- This lets a reclaimed worker distinguish a completed external operation from
-- a request that may still be running; it must still retrieve the result by key.
create or replace function public.mark_generation_provider_operation_result_received(
  p_job_id uuid,
  p_worker_id text,
  p_provider_request_id text default null
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare v_updated integer;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or (p_provider_request_id is not null
         and length(p_provider_request_id) not between 1 and 500) then
    raise exception 'Invalid provider result metadata' using errcode = '22023';
  end if;

  update public.generation_provider_operations as op
     set state = 'result_received',
         provider_request_id = coalesce(op.provider_request_id, p_provider_request_id),
         result_received_at = coalesce(result_received_at, now()),
         last_checked_at = now(),
         updated_at = now()
    from public.generation_jobs as job
   where op.job_id = p_job_id
     and job.id = op.job_id
     and job.status = 'running'
     and job.lease_owner = btrim(p_worker_id)
     and job.lease_expires_at > now()
     and op.state in ('submitting', 'accepted', 'unknown', 'result_received')
     and (op.provider_request_id is null or p_provider_request_id is null
          or op.provider_request_id = p_provider_request_id);

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

revoke all on function public.mark_generation_provider_operation_result_received(uuid, text, text) from public, anon, authenticated;
grant execute on function public.mark_generation_provider_operation_result_received(uuid, text, text) to service_role;
