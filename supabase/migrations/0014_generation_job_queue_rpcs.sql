-- PWA Studio: atomic queue RPCs for generation jobs.
-- REVIEW ONLY. Depends on migration 0013 and has NOT been applied to Supabase.
-- SECURITY DEFINER functions are backend-only; never expose service_role.

alter table public.generation_job_outbox
  add column if not exists claimed_by text,
  add column if not exists claim_expires_at timestamptz,
  add column if not exists dead_lettered_at timestamptz,
  add column if not exists last_error_code text
    check (last_error_code is null or char_length(last_error_code) <= 80);

-- Legacy claimed rows predate explicit expiry timestamps. Expire them at
-- migration time so they can be safely reclaimed instead of being stuck.
update public.generation_job_outbox
set claim_expires_at = now()
where claimed_at is not null and claim_token is not null and claim_expires_at is null;

do $
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.generation_job_outbox'::regclass
      and conname = 'generation_job_outbox_claim_expiry_consistency'
  ) then
    alter table public.generation_job_outbox
      add constraint generation_job_outbox_claim_expiry_consistency
      check (
        (claimed_at is null and claim_token is null and claim_expires_at is null)
        or
        (claimed_at is not null and claim_token is not null and claim_expires_at is not null)
      ) not valid;
  end if;
end;
$;

alter table public.generation_job_outbox
  validate constraint generation_job_outbox_claim_expiry_consistency;

create or replace function public.claim_generation_outbox(
  p_worker_id text, p_batch_size integer default 10, p_lease_seconds integer default 60
) returns table (outbox_id bigint, job_id uuid, event_type text, claim_token uuid, delivery_attempt integer)
language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_batch_size is null or p_batch_size not between 1 and 100
     or p_lease_seconds is null or p_lease_seconds not between 10 and 600 then
    raise exception 'invalid_claim_parameters' using errcode = '22023';
  end if;
  update public.generation_job_outbox
  set dead_lettered_at = now(),
      last_error_code = coalesce(last_error_code, 'delivery_attempt_limit_reached'),
      claimed_at = null, claimed_by = null, claim_token = null, claim_expires_at = null
  where delivered_at is null and dead_lettered_at is null and delivery_attempts >= 20
    and (claimed_at is null or claim_expires_at is null or claim_expires_at <= now());
  return query
  with candidates as (
    select o.id from public.generation_job_outbox o
    where o.delivered_at is null and o.dead_lettered_at is null
      and o.available_at <= now() and o.delivery_attempts < 20
      and (o.claimed_at is null or o.claim_expires_at is null or o.claim_expires_at <= now())
    order by o.available_at, o.id limit p_batch_size for update skip locked
  ), claimed as (
    update public.generation_job_outbox o
    set claimed_at = now(), claimed_by = p_worker_id, claim_token = gen_random_uuid(),
        claim_expires_at = now() + make_interval(secs => p_lease_seconds),
        delivery_attempts = o.delivery_attempts + 1
    from candidates c where o.id = c.id
    returning o.id, o.job_id, o.event_type, o.claim_token, o.delivery_attempts
  ) select c.id, c.job_id, c.event_type, c.claim_token, c.delivery_attempts from claimed c;
end;
$$;

create or replace function public.ack_generation_outbox(p_outbox_id bigint, p_claim_token uuid)
returns boolean language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_count integer;
begin
  update public.generation_job_outbox
  set delivered_at = now(), claimed_at = null, claimed_by = null, claim_token = null, claim_expires_at = null
  where id = p_outbox_id and claim_token = p_claim_token and delivered_at is null
    and dead_lettered_at is null and claim_expires_at > now();
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

create or replace function public.claim_generation_job(p_worker_id text, p_lease_seconds integer default 120)
returns setof public.generation_jobs language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_job_id uuid;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_lease_seconds is null or p_lease_seconds not between 10 and 900 then
    raise exception 'invalid_claim_parameters' using errcode = '22023';
  end if;
  update public.generation_jobs
  set status = 'failed', safe_error_code = 'attempt_limit_reached',
      completed_at = now(), updated_at = now(), next_attempt_at = null
  where status in ('queued','retry_wait') and attempt_count >= max_attempts
    and (next_attempt_at is null or next_attempt_at <= now());
  select j.id into v_job_id from public.generation_jobs j
  where j.status in ('queued','retry_wait')
    and (j.next_attempt_at is null or j.next_attempt_at <= now())
    and j.attempt_count < j.max_attempts
  order by j.created_at, j.id limit 1 for update skip locked;
  if v_job_id is null then return; end if;
  return query update public.generation_jobs j
  set status = 'processing', worker_id = p_worker_id, attempt_count = j.attempt_count + 1,
      lease_token = gen_random_uuid(), lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      next_attempt_at = null, started_at = coalesce(j.started_at, now()),
      updated_at = now(), safe_error_code = null
  where j.id = v_job_id and j.status in ('queued','retry_wait') returning j.*;
end;
$$;

create or replace function public.heartbeat_generation_job(p_job_id uuid, p_lease_token uuid, p_lease_seconds integer default 120)
returns boolean language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_count integer;
begin
  if p_lease_seconds is null or p_lease_seconds not between 10 and 900 then
    raise exception 'invalid_lease_seconds' using errcode = '22023';
  end if;
  update public.generation_jobs set lease_expires_at = now() + make_interval(secs => p_lease_seconds), updated_at = now()
  where id = p_job_id and lease_token = p_lease_token and status = 'processing' and lease_expires_at > now();
  get diagnostics v_count = row_count; return v_count = 1;
end;
$$;

create or replace function public.complete_generation_job(p_job_id uuid, p_lease_token uuid, p_result_asset_id uuid, p_actual_cost_usd numeric default null)
returns boolean language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_count integer;
begin
  if p_result_asset_id is null or (p_actual_cost_usd is not null and p_actual_cost_usd < 0) then
    raise exception 'invalid_completion_payload' using errcode = '22023';
  end if;
  update public.generation_jobs g set status = 'succeeded', result_asset_id = p_result_asset_id,
    actual_cost_usd = p_actual_cost_usd, completed_at = now(), updated_at = now(),
    worker_id = null, lease_token = null, lease_expires_at = null
  where g.id = p_job_id and g.lease_token = p_lease_token
    and g.status = 'processing' and g.lease_expires_at > now()
    and exists (
      select 1 from public.media_assets m
      where m.id = p_result_asset_id
        and m.owner_id = g.owner_id
        and m.storage_path is not null
    );
  get diagnostics v_count = row_count; return v_count = 1;
end;
$$;

create or replace function public.fail_generation_job(p_job_id uuid, p_lease_token uuid, p_safe_error_code text,
  p_retryable boolean, p_retry_delay_seconds integer default 30, p_actual_cost_usd numeric default null)
returns text language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_job public.generation_jobs%rowtype; v_status text;
begin
  if p_safe_error_code is null or length(p_safe_error_code) not between 1 and 80
     or p_safe_error_code !~ '^[a-zA-Z0-9_.-]+$'
     or p_retryable is null or p_retry_delay_seconds is null or p_retry_delay_seconds not between 1 and 3600
     or (p_actual_cost_usd is not null and p_actual_cost_usd < 0) then
    raise exception 'invalid_failure_payload' using errcode = '22023';
  end if;
  select * into v_job from public.generation_jobs
  where id = p_job_id and lease_token = p_lease_token and status = 'processing' and lease_expires_at > now() for update;
  if not found then return 'stale_lease'; end if;
  if p_retryable and v_job.attempt_count < v_job.max_attempts then
    v_status := 'retry_wait';
    update public.generation_jobs set status = v_status, safe_error_code = p_safe_error_code,
      actual_cost_usd = coalesce(p_actual_cost_usd, actual_cost_usd),
      next_attempt_at = now() + make_interval(secs => p_retry_delay_seconds),
      worker_id = null, lease_token = null, lease_expires_at = null, updated_at = now() where id = p_job_id;
    insert into public.generation_job_outbox(job_id, event_type, available_at)
      values (p_job_id, 'job_retry_ready', now() + make_interval(secs => p_retry_delay_seconds));
  else
    v_status := 'failed';
    update public.generation_jobs set status = v_status, safe_error_code = p_safe_error_code,
      actual_cost_usd = coalesce(p_actual_cost_usd, actual_cost_usd), completed_at = now(), next_attempt_at = null,
      worker_id = null, lease_token = null, lease_expires_at = null, updated_at = now() where id = p_job_id;
  end if;
  return v_status;
end;
$$;

create or replace function public.request_generation_job_cancel(p_job_id uuid, p_owner_id uuid)
returns text language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_job public.generation_jobs%rowtype;
begin
  if p_owner_id is null then raise exception 'owner_required' using errcode = '22023'; end if;
  select * into v_job from public.generation_jobs where id = p_job_id and owner_id = p_owner_id for update;
  if not found then return 'not_found'; end if;
  if v_job.status in ('succeeded','failed','cancelled') then return v_job.status; end if;
  if v_job.status = 'cancel_requested' then return 'cancel_requested'; end if;
  if v_job.status in ('queued','retry_wait') then
    update public.generation_jobs set status = 'cancelled', completed_at = now(), updated_at = now(), next_attempt_at = null where id = p_job_id;
    return 'cancelled';
  end if;
  if v_job.status = 'processing' then
    update public.generation_jobs set status = 'cancel_requested', cancel_requested_at = now(), updated_at = now() where id = p_job_id;
    insert into public.generation_job_outbox(job_id, event_type) values (p_job_id, 'job_cancel_requested');
    return 'cancel_requested';
  end if;
  return v_job.status;
end;
$$;

create or replace function public.recover_expired_generation_jobs(p_batch_size integer default 100)
returns integer language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_job public.generation_jobs%rowtype; v_count integer := 0;
begin
  if p_batch_size is null or p_batch_size not between 1 and 500 then
    raise exception 'invalid_batch_size' using errcode = '22023';
  end if;
  for v_job in select * from public.generation_jobs
    where status in ('processing','cancel_requested') and lease_expires_at <= now()
    order by lease_expires_at, id limit p_batch_size for update skip locked
  loop
    if v_job.status = 'cancel_requested' then
      update public.generation_jobs set status = 'cancelled', result_asset_id = null, completed_at = now(),
        updated_at = now(), worker_id = null, lease_token = null, lease_expires_at = null, next_attempt_at = null
      where id = v_job.id and lease_token = v_job.lease_token;
    elsif v_job.attempt_count < v_job.max_attempts then
      update public.generation_jobs set status = 'retry_wait', safe_error_code = 'worker_lease_expired',
        next_attempt_at = now(), updated_at = now(), worker_id = null, lease_token = null, lease_expires_at = null
      where id = v_job.id and lease_token = v_job.lease_token;
      insert into public.generation_job_outbox(job_id, event_type, available_at) values (v_job.id, 'job_retry_ready', now());
    else
      update public.generation_jobs set status = 'failed', safe_error_code = 'worker_lease_expired',
        completed_at = now(), updated_at = now(), worker_id = null, lease_token = null, lease_expires_at = null, next_attempt_at = null
      where id = v_job.id and lease_token = v_job.lease_token;
    end if;
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$$;

create or replace function public.finish_generation_job_cancel(p_job_id uuid, p_lease_token uuid)
returns boolean language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_count integer;
begin
  update public.generation_jobs set status = 'cancelled', result_asset_id = null, completed_at = now(),
    updated_at = now(), worker_id = null, lease_token = null, lease_expires_at = null, next_attempt_at = null
  where id = p_job_id and lease_token = p_lease_token and status = 'cancel_requested'
    and lease_expires_at > now();
  get diagnostics v_count = row_count; return v_count = 1;
end;
$$;

-- Privileged RPCs are executable only by the trusted backend service_role.
revoke all on function public.claim_generation_outbox(text, integer, integer) from public, anon, authenticated;
revoke all on function public.ack_generation_outbox(bigint, uuid) from public, anon, authenticated;
revoke all on function public.claim_generation_job(text, integer) from public, anon, authenticated;
revoke all on function public.heartbeat_generation_job(uuid, uuid, integer) from public, anon, authenticated;
revoke all on function public.complete_generation_job(uuid, uuid, uuid, numeric) from public, anon, authenticated;
revoke all on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) from public, anon, authenticated;
revoke all on function public.request_generation_job_cancel(uuid, uuid) from public, anon, authenticated;
revoke all on function public.recover_expired_generation_jobs(integer) from public, anon, authenticated;
revoke all on function public.finish_generation_job_cancel(uuid, uuid) from public, anon, authenticated;
grant execute on function public.claim_generation_outbox(text, integer, integer) to service_role;
grant execute on function public.ack_generation_outbox(bigint, uuid) to service_role;
grant execute on function public.claim_generation_job(text, integer) to service_role;
grant execute on function public.heartbeat_generation_job(uuid, uuid, integer) to service_role;
grant execute on function public.complete_generation_job(uuid, uuid, uuid, numeric) to service_role;
grant execute on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) to service_role;
grant execute on function public.request_generation_job_cancel(uuid, uuid) to service_role;
grant execute on function public.recover_expired_generation_jobs(integer) to service_role;
grant execute on function public.finish_generation_job_cancel(uuid, uuid) to service_role;

comment on function public.claim_generation_job(text, integer) is 'Atomically claims one due job and assigns a fresh lease fencing token. Backend service_role only.';
comment on function public.recover_expired_generation_jobs(integer) is 'Recovers expired leases: cancellations complete; other jobs retry or fail at the attempt limit.';
comment on function public.fail_generation_job(uuid, uuid, text, boolean, integer, numeric) is 'Fenced failure transition; retryable failures atomically enqueue a retry outbox event.';
comment on function public.request_generation_job_cancel(uuid, uuid) is 'Owner-scoped cancellation. Backend must derive p_owner_id from the verified Supabase JWT.';