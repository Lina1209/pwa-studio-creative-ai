-- Structured worker heartbeat and fenced cancellation acknowledgement.
-- Running cancellation stays leased until provider operation is definitively reconciled.

drop function if exists public.heartbeat_generation_job(uuid, text, integer);

create or replace function public.heartbeat_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_lease_seconds integer default 180
)
returns text
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
    raise exception 'Invalid worker identity or lease duration' using errcode = '22023';
  end if;

  select * into v_job
    from public.generation_jobs
   where id = p_job_id
   for update;

  if not found then
    return 'lease_lost';
  end if;

  if v_job.status in ('succeeded', 'failed', 'cancelled', 'expired') then
    return 'terminal';
  end if;

  if v_job.lease_owner is distinct from btrim(p_worker_id)
     or v_job.lease_expires_at is null
     or v_job.lease_expires_at <= now() then
    return 'lease_lost';
  end if;

  if v_job.status = 'cancel_requested' then
    update public.generation_jobs
       set heartbeat_at = now(),
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           updated_at = now()
     where id = p_job_id;
    return 'cancel_requested';
  end if;

  if v_job.status = 'running' then
    update public.generation_jobs
       set heartbeat_at = now(),
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           updated_at = now()
     where id = p_job_id;
    return 'active';
  end if;

  return 'lease_lost';
end;
$$;

create or replace function public.acknowledge_generation_job_cancellation(
  p_job_id uuid,
  p_worker_id text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_operation_state text;
  v_hold_id uuid;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'Invalid cancellation acknowledgement metadata'
      using errcode = '22023';
  end if;

  -- Lock order is job -> provider journal -> credit hold/wallet.
  select * into v_job
    from public.generation_jobs
   where id = p_job_id
   for update;

  if not found
     or v_job.status <> 'cancel_requested'
     or v_job.lease_owner is distinct from btrim(p_worker_id)
     or v_job.lease_expires_at is null
     or v_job.lease_expires_at <= now() then
    return false;
  end if;

  select op.state into v_operation_state
    from public.generation_provider_operations op
   where op.job_id = p_job_id
   for update;

  -- No journal means provider submission was never durably begun. Otherwise
  -- only a definitive provider failure or a received result is reconcilable.
  if found and v_operation_state not in ('provider_failed', 'result_received') then
    return false;
  end if;

  update public.generation_jobs
     set status = 'cancelled',
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         last_error_code = 'user_cancelled',
         updated_at = now()
   where id = p_job_id;

  select h.id into v_hold_id
    from public.credit_holds h
   where h.job_id = p_job_id
     and h.user_id = v_job.user_id
     and h.status = 'held'
   for update;

  if v_hold_id is not null then
    perform public.release_job_credit_hold(
      v_job.user_id, v_hold_id, 'user_cancelled'
    );
  end if;

  return true;
end;
$$;

revoke all on function public.heartbeat_generation_job(uuid, text, integer)
  from public, anon, authenticated;
revoke all on function public.acknowledge_generation_job_cancellation(uuid, text)
  from public, anon, authenticated;

grant execute on function public.heartbeat_generation_job(uuid, text, integer)
  to service_role;
grant execute on function public.acknowledge_generation_job_cancellation(uuid, text)
  to service_role;

comment on function public.heartbeat_generation_job(uuid, text, integer) is
  'Returns active, cancel_requested, terminal, or lease_lost; renews only the matching unexpired worker lease.';
comment on function public.acknowledge_generation_job_cancellation(uuid, text) is
  'Fenced worker acknowledgement. Cancels and releases credits only after no provider journal exists or its state is provider_failed/result_received.';


-- Provider calls already in flight may finish after cancellation is requested.
-- Permit the lease owner to journal their definitive outcome, but never to begin
-- a new provider operation after the job has entered cancel_requested.
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
     and job.status in ('running', 'cancel_requested')
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
     and job.status in ('running', 'cancel_requested')
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
     and job.status in ('running', 'cancel_requested')
     and job.lease_owner = btrim(p_worker_id)
     and job.lease_expires_at > now()
     and op.state in ('submitting', 'accepted', 'unknown', 'provider_failed');

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

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
     and job.status in ('running', 'cancel_requested')
     and job.lease_owner = btrim(p_worker_id)
     and job.lease_expires_at > now()
     and op.state in ('submitting', 'accepted', 'unknown', 'result_received')
     and (op.provider_request_id is null or p_provider_request_id is null
          or op.provider_request_id = p_provider_request_id);

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;


-- Reclaim expired cancellation leases for provider-state reconciliation.
-- Cancellation jobs retain their status and do not consume another generation attempt.
create or replace function public.claim_next_generation_job_v2(
  p_worker_id text,
  p_lease_seconds integer default 180
)
returns table (
  job_id uuid,
  user_id uuid,
  studio_scene_id uuid,
  job_type text,
  provider text,
  model text,
  request_snapshot jsonb,
  attempt_count integer,
  max_attempts integer,
  lease_expires_at timestamptz,
  job_status text
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'worker_id must contain 1 to 120 characters' using errcode = '22023';
  end if;
  if p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
    raise exception 'lease_seconds must be between 30 and 3600' using errcode = '22023';
  end if;

  -- Expired ordinary generation attempts are terminal after their retry budget.
  -- Cancellation reconciliation is not a new generation attempt and remains claimable.
  update public.generation_jobs as expired
     set status = 'failed',
         last_error_code = 'worker_lease_expired',
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         updated_at = now()
   where expired.status = 'running'
     and expired.lease_expires_at <= now()
     and expired.attempt_count >= expired.max_attempts;

  return query
  with candidate as (
    select j.id
      from public.generation_jobs as j
     where (
       j.status in ('queued', 'retry_wait') and j.available_at <= now()
     ) or (
       j.status in ('running', 'cancel_requested')
       and j.lease_expires_at <= now()
     )
     order by case when j.status = 'cancel_requested' then 0 else 1 end,
              j.available_at, j.created_at, j.id
     for update skip locked
     limit 1
  ),
  claimed as (
    update public.generation_jobs as j
       set status = case
             when j.status = 'cancel_requested' then 'cancel_requested'
             else 'running'
           end,
           attempt_count = case
             when j.status = 'cancel_requested' then j.attempt_count
             else j.attempt_count + 1
           end,
           lease_owner = btrim(p_worker_id),
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           heartbeat_at = now(),
           started_at = coalesce(j.started_at, now()),
           completed_at = null,
           last_error_code = case
             when j.status = 'running' then 'worker_lease_expired'
             when j.status = 'cancel_requested' then 'user_cancel_requested'
             else j.last_error_code
           end,
           updated_at = now()
      from candidate as c
     where j.id = c.id
     returning j.id, j.user_id, j.studio_scene_id, j.job_type,
               j.provider, j.model, j.request_snapshot,
               j.attempt_count, j.max_attempts, j.lease_expires_at, j.status
  )
  select c.id, c.user_id, c.studio_scene_id, c.job_type,
         c.provider, c.model, c.request_snapshot,
         c.attempt_count, c.max_attempts, c.lease_expires_at, c.status
    from claimed as c;
end;
$$;

revoke all on function public.claim_next_generation_job_v2(text, integer)
  from public, anon, authenticated;
grant execute on function public.claim_next_generation_job_v2(text, integer)
  to service_role;

comment on function public.claim_next_generation_job_v2(text, integer) is
  'Claims normal generation jobs or reclaims expired cancellation leases without incrementing generation attempts; cancellation status is preserved for provider reconciliation.';
