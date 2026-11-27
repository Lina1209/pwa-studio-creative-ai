-- PWA Studio: atomic queue RPCs for generation jobs.
-- REVIEW ONLY. Depends on migration 0013 and has NOT been applied to Supabase.
-- These SECURITY DEFINER functions are backend-only; never expose service_role.

alter table public.generation_job_outbox
  add column if not exists claimed_by text,
  add column if not exists dead_lettered_at timestamptz,
  add column if not exists last_error_code text
    check (last_error_code is null or char_length(last_error_code) <= 80);

create or replace function public.claim_generation_outbox(
  p_worker_id text,
  p_batch_size integer default 10,
  p_lease_seconds integer default 60
)
returns table (
  outbox_id bigint,
  job_id uuid,
  event_type text,
  claim_token uuid,
  delivery_attempt integer
)
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'invalid_worker_id' using errcode = '22023';
  end if;
  if p_batch_size is null or p_batch_size < 1 or p_batch_size > 100 then
    raise exception 'invalid_batch_size' using errcode = '22023';
  end if;
  if p_lease_seconds is null or p_lease_seconds < 10 or p_lease_seconds > 600 then
    raise exception 'invalid_lease_seconds' using errcode = '22023';
  end if;

  -- Poisoned events that exhausted delivery attempts are explicitly dead-lettered.
  update public.generation_job_outbox
  set dead_lettered_at = now(),
      last_error_code = coalesce(last_error_code, 'delivery_attempt_limit_reached'),
      claimed_at = null,
      claimed_by = null,
      claim_token = null
  where delivered_at is null
    and dead_lettered_at is null
    and delivery_attempts >= 20
    and (claimed_at is null or claimed_at < now() - make_interval(secs => p_lease_seconds));

  return query
  with candidates as (
    select o.id
    from public.generation_job_outbox o
    where o.delivered_at is null
      and o.available_at <= now()
      and (o.claimed_at is null or o.claimed_at < now() - make_interval(secs => p_lease_seconds))
      and o.delivery_attempts < 20
    order by o.available_at, o.id
    for update skip locked
    limit p_batch_size
  ),
  claimed as (
    update public.generation_job_outbox o
    set claimed_at = now(),
        claimed_by = p_worker_id,
        claim_token = gen_random_uuid(),
        delivery_attempts = o.delivery_attempts + 1
    from candidates c
    where o.id = c.id
    returning o.id, o.job_id, o.event_type, o.claim_token, o.delivery_attempts
  )
  select c.id, c.job_id, c.event_type, c.claim_token, c.delivery_attempts
  from claimed c;
end;
$$;

create or replace function public.ack_generation_outbox(
  p_outbox_id bigint,
  p_claim_token uuid
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_count integer;
begin
  update public.generation_job_outbox
  set delivered_at = now(), claimed_at = null, claimed_by = null, claim_token = null
  where id = p_outbox_id
    and claim_token = p_claim_token
    and delivered_at is null;
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

create or replace function public.claim_generation_job(
  p_worker_id text,
  p_lease_seconds integer default 120
)
returns setof public.generation_jobs
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_job_id uuid;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'invalid_worker_id' using errcode = '22023';
  end if;
  if p_lease_seconds is null or p_lease_seconds < 10 or p_lease_seconds > 900 then
    raise exception 'invalid_lease_seconds' using errcode = '22023';
  end if;

  -- Close exhausted queued jobs rather than allowing an unclaimable queue item.
  update public.generation_jobs
  set status = 'failed',
      safe_error_code = 'attempt_limit_reached',
      completed_at = now(),
      updated_at = now(),
      next_attempt_at = null
  where status in ('queued','retry_wait')
    and attempt_count >= max_attempts
    and (next_attempt_at is null or next_attempt_at <= now());

  select j.id into v_job_id
  from public.generation_jobs j
  where j.status in ('queued','retry_wait')
    and (j.next_attempt_at is null or j.next_attempt_at <= now())
    and j.attempt_count < j.max_attempts
  order by j.created_at, j.id
  for update skip locked
  limit 1;

  if v_job_id is null then
    return;
  end if;

  return query
  update public.generation_jobs j
  set status = 'processing',
      worker_id = p_worker_id,
      attempt_count = j.attempt_count + 1,
      lease_token = gen_random_uuid(),
      lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      next_attempt_at = null,
      started_at = coalesce(j.started_at, now()),
      updated_at = now(),
      safe_error_code = null
  where j.id = v_job_id
    and j.status in ('queued','retry_wait')
  returning j.*;
end;
$$;

create or replace function public.heartbeat_generation_job(
  p_job_id uuid,
  p_lease_token uuid,
  p_lease_seconds integer default 120
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_count integer;
begin
  if p_lease_seconds < 10 or p_lease_seconds > 900 then
    raise exception 'invalid_lease_seconds' using errcode = '22023';
  end if;
  update public.generation_jobs
  set lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      updated_at = now()
  where id = p_job_id
    and lease_token = p_lease_token
    and status = 'processing'
    and lease_expires_at > now();
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

create or replace function public.complete_generation_job(
  p_job_id uuid,
  p_lease_token uuid,
  p_result_asset_id uuid,
  p_actual_cost_usd numeric default null
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_count integer;
begin
  if p_result_asset_id is null then
    raise exception 'result_asset_required' using errcode = '22023';
  end if;
  if p_actual_cost_usd is not null and p_actual_cost_usd < 0 then
    raise exception 'invalid_actual_cost' using errcode = '22023';
  end if;

  update public.generation_jobs
  set status = 'succeeded',
      result_asset_id = p_result_asset_id,
      actual_cost_usd = p_actual_cost_usd,
      completed_at = now(),
      updated_at = now(),
      worker_id = null,
      lease_token = null,
      lease_expires_at = null
  where id = p_job_id
    and lease_token = p_lease_token
    and status = 'processing'
    and lease_expires_at > now();
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

create or replace function public.fail_generation_job(
  p_job_id uuid,
  p_lease_token uuid,
  p_safe_error_code text,
  p_retryable boolean,
  p_retry_delay_seconds integer default 30,
  p_actual_cost_usd numeric default null
)
returns text
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_new_status text;
begin
  if p_safe_error_code is null or length(p_safe_error_code) not between 1 and 80
     or p_safe_error_code !~ '^[a-zA-Z0-9_.-]+$' then
    raise exception 'invalid_safe_error_code' using errcode = '22023';
  end if;
  if p_retry_delay_seconds is null or p_retry_delay_seconds < 1 or p_retry_delay_seconds > 3600 then
    raise exception 'invalid_retry_delay' using errcode = '22023';
  end if;
  if p_actual_cost_usd is not null and p_actual_cost_usd < 0 then
    raise exception 'invalid_actual_cost' using errcode = '22023';
  end if;

  select * into v_job
  from public.generation_jobs
  where id = p_job_id
    and lease_token = p_lease_token
    and status = 'processing'
    and lease_expires_at > now()
  for update;

  if not found then
    return 'stale_lease';
  end if;

  if p_retryable is true and v_job.attempt_count < v_job.max_attempts then
    v_new_status := 'retry_wait';
    update public.generation_jobs
    set status = v_new_status,
        safe_error_code = p_safe_error_code,
        actual_cost_usd = coalesce(p_actual_cost_usd, actual_cost_usd),
        next_attempt_at = now() + make_interval(secs => p_retry_delay_seconds),
        worker_id = null, lease_token = null, lease_expires_at = null,
        updated_at = now()
    where id = p_job_id;

    insert into public.generation_job_outbox(job_id, event_type, available_at)
    values (p_job_id, 'job_retry_ready', now() + make_interval(secs => p_retry_delay_seconds));
  else
    v_new_status := 'failed';
    update public.generation_jobs
    set status = v_new_status,
        safe_error_code = p_safe_error_code,
        actual_cost_usd = coalesce(p_actual_cost_usd, actual_cost_usd),
        completed_at = now(),
        next_attempt_at = null,
        worker_id = null, lease_token = null, lease_expires_at = null,
        updated_at = now()
    where id = p_job_id;
  end if;

  return v_new_status;
end;
$$;

create or replace function public.request_generation_job_cancel(
  p_job_id uuid,
  p_owner_id uuid
)
returns text
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_job public.generation_jobs%rowtype;
begin
  if p_owner_id is null then
    raise exception 'owner_required' using errcode = '22023';
  end if;

  select * into v_job
  from public.generation_jobs
  where id = p_job_id and owner_id = p_owner_id
  for update;

  if not found then
    return 'not_found';
  end if;
  if v_job.status in ('succeeded','failed','cancelled') then
    return v_job.status;
  end if;
  if v_job.status = 'cancel_requested' then
    return 'cancel_requested';
  end if;

  if v_job.status in ('queued','retry_wait') then
    update public.generation_jobs
    set status = 'cancelled', completed_at = now(), updated_at = now(),
        next_attempt_at = null
    where id = p_job_id;
    return 'cancelled';
  end if;

  if v_job.status = 'processing' then
    update public.generation_jobs
    set status = 'cancel_requested', cancel_requested_at = now(), updated_at = now()
    where id = p_job_id;
    insert into public.generation_job_outbox(job_id, event_type)
    values (p_job_id, 'job_cancel_requested');
    return 'cancel_requested';
  end if;

  return v_job.status;
end;
$$;


create or replace function public.recover_expired_generation_jobs(
  p_batch_size integer default 100
)
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $
declare
  v_job public.generation_jobs%rowtype;
  v_count integer := 0;
begin
  if p_batch_size is null or p_batch_size < 1 or p_batch_size > 500 then
    raise exception 'invalid_batch_size' using errcode = '22023';
  end if;

  for v_job in
    select *
    from public.generation_jobs
    where status in ('processing','cancel_requested')
      and lease_expires_at <= now()
    order by lease_expires_at, id
    for update skip locked
    limit p_batch_size
  loop
    if v_job.status = 'cancel_requested' then
      update public.generation_jobs
      set status = 'cancelled',
          result_asset_id = null,
          completed_at = now(),
          updated_at = now(),
          worker_id = null,
          lease_token = null,
          lease_expires_at = null,
          next_attempt_at = null
      where id = v_job.id and lease_token = v_job.lease_token;
    elsif v_job.attempt_count < v_job.max_attempts then
      update public.generation_jobs
      set status = 'retry_wait',
          safe_error_code = 'worker_lease_expired',
          next_attempt_at = now(),
          updated_at = now(),
          worker_id = null,
          lease_token = null,
          lease_expires_at = null
      where id = v_job.id and lease_token = v_job.lease_token;

      insert into public.generation_job_outbox(job_id, event_type, available_at)
      values (v_job.id, 'job_retry_ready', now());
    else
      update public.generation_jobs
      set status = 'failed',
          safe_error_code = 'worker_lease_expired',
          completed_at = now(),
          updated_at = now(),
          worker_id = null,
          lease_token = null,
          lease_expires_at = null,
          next_attempt_at = null
      where id = v_job.id and lease_token = v_job.lease_token;
    end if;
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$;

create or replace function public.fail_generation_outbox(
  p_outbox_id bigint,
  p_claim_token uuid,
  p_safe_error_code text,
  p_retry_delay_seconds integer default 30
)
returns text
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $
declare
  v_row public.generation_job_outbox%rowtype;
begin
  if p_safe_error_code is null or length(p_safe_error_code) not between 1 and 80
     or p_safe_error_code !~ '^[a-zA-Z0-9_.-]+
  p_job_id uuid,
  p_lease_token uuid
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_count integer;
begin
  update public.generation_jobs
  set status = 'cancelled',
      result_asset_id = null,
      completed_at = now(),
      updated_at = now(),
      worker_id = null,
      lease_token = null,
      lease_expires_at = null,
      next_attempt_at = null
  where id = p_job_id
    and lease_token = p_lease_token
    and status = 'cancel_requested';
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

-- Only the trusted backend service role may invoke these privileged functions.
revoke all on function public.fail_generation_outbox(bigint, uuid, text, integer) from public, anon, authenticated;
revoke all on function public.recover_expired_generation_jobs(integer) from public, anon, authenticated;
revoke all on function public.claim_generation_outbox(text, integer, integer) from public, anon, authenticated;
revoke all on function public.ack_generation_outbox(bigint, uuid) from public, anon, authenticated;
revoke all on function public.claim_generation_job(text, integer) from public, anon, authenticated;
revoke all on function public.heartbeat_generation_job(uuid, uuid, integer) from public, anon, authenticated;
revoke all on function public.complete_generation_job(uuid, uuid, uuid, numeric) from public, anon, authenticated;
revoke all on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) from public, anon, authenticated;
revoke all on function public.request_generation_job_cancel(uuid, uuid) from public, anon, authenticated;
revoke all on function public.finish_generation_job_cancel(uuid, uuid) from public, anon, authenticated;

grant execute on function public.fail_generation_outbox(bigint, uuid, text, integer) to service_role;
grant execute on function public.recover_expired_generation_jobs(integer) to service_role;
grant execute on function public.claim_generation_outbox(text, integer, integer) to service_role;
grant execute on function public.ack_generation_outbox(bigint, uuid) to service_role;
grant execute on function public.claim_generation_job(text, integer) to service_role;
grant execute on function public.heartbeat_generation_job(uuid, uuid, integer) to service_role;
grant execute on function public.complete_generation_job(uuid, uuid, uuid, numeric) to service_role;
grant execute on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) to service_role;
grant execute on function public.request_generation_job_cancel(uuid, uuid) to service_role;
grant execute on function public.finish_generation_job_cancel(uuid, uuid) to service_role;

comment on function public.recover_expired_generation_jobs(integer) is
  'Recovers expired leases: cancellation completes as cancelled; other jobs retry or fail at the attempt limit.';
comment on function public.claim_generation_job(text, integer) is
  'Atomically claims one due job and assigns a fresh lease fencing token. Backend service_role only.';
comment on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) is
  'Fenced failure transition; retryable failures atomically enqueue a retry outbox event.';
comment on function public.request_generation_job_cancel(uuid, uuid) is
  'Owner-scoped cancellation transition. Caller must derive p_owner_id from verified Supabase JWT.';
 then
    raise exception 'invalid_safe_error_code' using errcode = '22023';
  end if;
  if p_retry_delay_seconds is null or p_retry_delay_seconds < 1 or p_retry_delay_seconds > 3600 then
    raise exception 'invalid_retry_delay' using errcode = '22023';
  end if;

  select * into v_row
  from public.generation_job_outbox
  where id = p_outbox_id and claim_token = p_claim_token and delivered_at is null
  for update;

  if not found then
    return 'stale_claim';
  end if;

  if v_row.delivery_attempts >= 20 then
    update public.generation_job_outbox
    set dead_lettered_at = now(),
        last_error_code = p_safe_error_code,
        claimed_at = null,
        claimed_by = null,
        claim_token = null
    where id = p_outbox_id and claim_token = p_claim_token;
    return 'dead_lettered';
  end if;

  update public.generation_job_outbox
  set available_at = now() + make_interval(secs => p_retry_delay_seconds),
      last_error_code = p_safe_error_code,
      claimed_at = null,
      claimed_by = null,
      claim_token = null
  where id = p_outbox_id and claim_token = p_claim_token;
  return 'retry_scheduled';
end;
$;

create or replace function public.finish_generation_job_cancel(
  p_job_id uuid,
  p_lease_token uuid
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_count integer;
begin
  update public.generation_jobs
  set status = 'cancelled',
      result_asset_id = null,
      completed_at = now(),
      updated_at = now(),
      worker_id = null,
      lease_token = null,
      lease_expires_at = null,
      next_attempt_at = null
  where id = p_job_id
    and lease_token = p_lease_token
    and status = 'cancel_requested';
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

-- Only the trusted backend service role may invoke these privileged functions.
revoke all on function public.claim_generation_outbox(text, integer, integer) from public, anon, authenticated;
revoke all on function public.ack_generation_outbox(bigint, uuid) from public, anon, authenticated;
revoke all on function public.claim_generation_job(text, integer) from public, anon, authenticated;
revoke all on function public.heartbeat_generation_job(uuid, uuid, integer) from public, anon, authenticated;
revoke all on function public.complete_generation_job(uuid, uuid, uuid, numeric) from public, anon, authenticated;
revoke all on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) from public, anon, authenticated;
revoke all on function public.request_generation_job_cancel(uuid, uuid) from public, anon, authenticated;
revoke all on function public.finish_generation_job_cancel(uuid, uuid) from public, anon, authenticated;

grant execute on function public.claim_generation_outbox(text, integer, integer) to service_role;
grant execute on function public.ack_generation_outbox(bigint, uuid) to service_role;
grant execute on function public.claim_generation_job(text, integer) to service_role;
grant execute on function public.heartbeat_generation_job(uuid, uuid, integer) to service_role;
grant execute on function public.complete_generation_job(uuid, uuid, uuid, numeric) to service_role;
grant execute on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) to service_role;
grant execute on function public.request_generation_job_cancel(uuid, uuid) to service_role;
grant execute on function public.finish_generation_job_cancel(uuid, uuid) to service_role;

comment on function public.claim_generation_job(text, integer) is
  'Atomically claims one due job and assigns a fresh lease fencing token. Backend service_role only.';
comment on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) is
  'Fenced failure transition; retryable failures atomically enqueue a retry outbox event.';
comment on function public.request_generation_job_cancel(uuid, uuid) is
  'Owner-scoped cancellation transition. Caller must derive p_owner_id from verified Supabase JWT.';
