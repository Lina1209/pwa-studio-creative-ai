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
