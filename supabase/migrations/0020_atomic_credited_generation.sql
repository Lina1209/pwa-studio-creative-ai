-- PWA Studio: atomic paid-job admission and atomic successful capture.
-- These are database primitives only. No endpoint, pricing catalog, payment flow,
-- worker deployment, or production migration is enabled by this file.

create or replace function public.create_credited_generation_job_with_outbox(
  p_user_id uuid,
  p_project_id uuid,
  p_studio_scene_id uuid,
  p_job_type text,
  p_provider text,
  p_model text,
  p_idempotency_key text,
  p_request_hash text,
  p_request_snapshot jsonb,
  p_quote_snapshot jsonb,
  p_credit_amount bigint
)
returns table(
  job_id uuid,
  event_id uuid,
  hold_id uuid,
  available_credits bigint,
  reserved_credits bigint,
  created boolean,
  replayed boolean
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job_id uuid;
  v_event_id uuid;
  v_hold public.credit_holds%rowtype;
  v_wallet public.credit_wallets%rowtype;
  v_existing public.generation_jobs%rowtype;
  v_created boolean := false;
begin
  if p_user_id is null
     or p_job_type not in ('image_generation', 'video_generation', 'audio_generation',
                           'speech_generation', 'ai_processing', 'media_export')
     or p_provider is null or length(btrim(p_provider)) not between 1 and 100
     or p_model is null or length(btrim(p_model)) not between 1 and 200
     or p_idempotency_key is null or length(p_idempotency_key) not between 8 and 200
     or p_request_hash is null or p_request_hash !~ '^[0-9a-f]{32,128}$'
     or p_credit_amount is null or p_credit_amount <= 0 or p_credit_amount > 1000000000000
     or p_request_snapshot is null or jsonb_typeof(p_request_snapshot) <> 'object'
     or octet_length(p_request_snapshot::text) > 65536
     or p_quote_snapshot is null or jsonb_typeof(p_quote_snapshot) <> 'object'
     or octet_length(p_quote_snapshot::text) > 16384 then
    raise exception 'Invalid credited generation job parameters' using errcode = '22023';
  end if;
  if p_project_id is not null and p_studio_scene_id is not null then
    raise exception 'A job cannot be linked to both a cloud project and a studio scene' using errcode = '22023';
  end if;

  insert into public.generation_jobs(
    user_id, project_id, studio_scene_id, job_type, provider, model,
    idempotency_key, request_hash, request_snapshot, pricing_snapshot
  ) values (
    p_user_id, p_project_id, p_studio_scene_id, p_job_type,
    btrim(p_provider), btrim(p_model), p_idempotency_key, p_request_hash,
    p_request_snapshot, p_quote_snapshot
  )
  on conflict (user_id, idempotency_key) do nothing
  returning id into v_job_id;

  v_created := v_job_id is not null;
  if not v_created then
    select * into v_existing from public.generation_jobs
     where user_id = p_user_id and idempotency_key = p_idempotency_key
     for update;
    if not found then
      raise exception 'Idempotency conflict could not be resolved; retry the request'
        using errcode = '40001';
    end if;
    if v_existing.request_hash <> p_request_hash
       or v_existing.project_id is distinct from p_project_id
       or v_existing.studio_scene_id is distinct from p_studio_scene_id
       or v_existing.job_type <> p_job_type
       or v_existing.provider <> btrim(p_provider)
       or v_existing.model <> btrim(p_model)
       or v_existing.request_snapshot <> p_request_snapshot
       or v_existing.pricing_snapshot <> p_quote_snapshot then
      raise exception 'Idempotency key was already used for a different generation request or quote'
        using errcode = '22023';
    end if;

    select * into v_hold from public.credit_holds
     where user_id = p_user_id and job_id = v_existing.id
     for update;
    if not found or v_hold.amount <> p_credit_amount
       or v_hold.operation_key <> p_idempotency_key
       or v_hold.quote_snapshot <> p_quote_snapshot then
      raise exception 'Existing generation job does not have the matching credit hold'
        using errcode = '55000';
    end if;

    select e.event_id into v_event_id
      from public.outbox_events e
     where e.aggregate_type = 'generation_job'
       and e.aggregate_id = v_existing.id
       and e.event_type = 'generation_job.created'
     order by e.id limit 1;
    if v_event_id is null then
      raise exception 'Existing generation job is missing its creation event'
        using errcode = '55000';
    end if;

    select * into v_wallet from public.credit_wallets
     where user_id = p_user_id for update;
    return query select v_existing.id, v_event_id, v_hold.id,
      v_wallet.available_credits, v_wallet.reserved_credits, false, true;
    return;
  end if;

  insert into public.outbox_events(aggregate_type, aggregate_id, event_type, payload)
  values (
    'generation_job', v_job_id, 'generation_job.created',
    jsonb_build_object('job_id', v_job_id, 'credited', true)
      || case when p_studio_scene_id is not null
              then jsonb_build_object('studio_scene_id', p_studio_scene_id)
              else '{}'::jsonb end
  )
  returning outbox_events.event_id into v_event_id;

  insert into public.credit_wallets(user_id) values (p_user_id)
  on conflict (user_id) do nothing;
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;

  if v_wallet.available_credits < p_credit_amount then
    raise exception 'Insufficient available credits' using errcode = 'P0001';
  end if;

  update public.credit_wallets
     set available_credits = available_credits - p_credit_amount,
         reserved_credits = reserved_credits + p_credit_amount,
         updated_at = now()
   where id = v_wallet.id
   returning * into v_wallet;

  insert into public.credit_holds(
    user_id, job_id, amount, quote_snapshot, operation_key
  ) values (
    p_user_id, v_job_id, p_credit_amount, p_quote_snapshot, p_idempotency_key
  ) returning * into v_hold;

  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, v_hold.id, 'reserve', 'reserve:' || p_idempotency_key,
    -p_credit_amount, p_credit_amount,
    v_wallet.available_credits, v_wallet.reserved_credits,
    jsonb_build_object('job_id', v_job_id, 'quote_snapshot', p_quote_snapshot)
  );

  return query select v_job_id, v_event_id, v_hold.id,
    v_wallet.available_credits, v_wallet.reserved_credits, true, false;
end;
$$;

create or replace function public.complete_credited_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_result_storage_path text
)
returns table(completed boolean, replayed boolean,
              available_credits bigint, reserved_credits bigint)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_hold public.credit_holds%rowtype;
  v_wallet public.credit_wallets%rowtype;
  v_entry public.credit_ledger%rowtype;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_result_storage_path is null
     or length(p_result_storage_path) not between 1 and 1024
     or left(p_result_storage_path, 1) = '/'
     or position('..' in p_result_storage_path) > 0 then
    raise exception 'Invalid credited completion parameters' using errcode = '22023';
  end if;

  select * into v_job from public.generation_jobs
   where id = p_job_id for update;
  if not found then raise exception 'Generation job not found' using errcode = 'P0002'; end if;

  -- A repeated completion is accepted only when the exact result path and
  -- captured hold are already recorded; it never mutates balances a second time.
  if v_job.status = 'succeeded' then
    if v_job.result_storage_path is distinct from p_result_storage_path then
      raise exception 'Completed job result path does not match replay' using errcode = '22023';
    end if;
    select * into v_hold from public.credit_holds
     where job_id = p_job_id and user_id = v_job.user_id;
    if not found or v_hold.status <> 'captured' then
      raise exception 'Successful credited job is missing its captured hold' using errcode = '55000';
    end if;
    select * into v_entry from public.credit_ledger
     where hold_id = v_hold.id and operation_type = 'capture';
    if not found then
      raise exception 'Successful credited job is missing its capture ledger entry' using errcode = '55000';
    end if;
    select * into v_wallet from public.credit_wallets
     where user_id = v_job.user_id;
    return query select true, true, v_wallet.available_credits, v_wallet.reserved_credits;
    return;
  end if;

  if v_job.status <> 'running'
     or v_job.lease_owner is distinct from btrim(p_worker_id)
     or v_job.lease_expires_at is null or v_job.lease_expires_at <= now()
     or left(p_result_storage_path, length(v_job.user_id::text) + 1)
          <> v_job.user_id::text || '/' then
    return query select false, false, null::bigint, null::bigint;
    return;
  end if;

  select * into v_hold from public.credit_holds
   where job_id = p_job_id and user_id = v_job.user_id
   for update;
  if not found or v_hold.status <> 'held' then
    raise exception 'Active credited generation job has no held credit reservation'
      using errcode = '55000';
  end if;

  select * into v_wallet from public.credit_wallets
   where user_id = v_job.user_id for update;
  if not found or v_wallet.reserved_credits < v_hold.amount then
    raise exception 'Wallet reserved balance is inconsistent with the credit hold'
      using errcode = '23514';
  end if;

  update public.credit_wallets
     set reserved_credits = reserved_credits - v_hold.amount,
         updated_at = now()
   where id = v_wallet.id
   returning * into v_wallet;

  update public.credit_holds
     set status = 'captured', captured_at = now(), updated_at = now()
   where id = v_hold.id;

  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    v_job.user_id, v_hold.id, 'capture', 'capture:' || v_hold.operation_key,
    0, -v_hold.amount,
    v_wallet.available_credits, v_wallet.reserved_credits,
    jsonb_build_object('job_id', p_job_id, 'result_storage_path', p_result_storage_path)
  );

  update public.generation_jobs
     set status = 'succeeded',
         result_storage_path = p_result_storage_path,
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         updated_at = now()
   where id = p_job_id;

  return query select true, false, v_wallet.available_credits, v_wallet.reserved_credits;
end;
$$;

-- Release is permitted only after the linked generation job is terminal.
create or replace function public.release_job_credit_hold(
  p_user_id uuid,
  p_hold_id uuid,
  p_reason_code text
)
returns table(available_credits bigint, reserved_credits bigint, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_wallet public.credit_wallets%rowtype;
  v_hold public.credit_holds%rowtype;
  v_entry public.credit_ledger%rowtype;
  v_key text;
begin
  if p_user_id is null or p_hold_id is null
     or p_reason_code is null or p_reason_code !~ '^[a-z0-9_]{3,64}$' then
    raise exception 'Invalid credit hold release parameters' using errcode = '22023';
  end if;

  select h.* into v_hold from public.credit_holds h
   where h.id = p_hold_id and h.user_id = p_user_id;
  if not found then raise exception 'Credit hold not found for owner' using errcode = 'P0002'; end if;

  select * into v_job from public.generation_jobs
   where id = v_hold.job_id and user_id = p_user_id for update;
  if not found then raise exception 'Generation job for credit hold was not found' using errcode = 'P0002'; end if;

  insert into public.credit_wallets(user_id) values (p_user_id)
  on conflict (user_id) do nothing;
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;
  select * into v_hold from public.credit_holds
   where id = p_hold_id and user_id = p_user_id for update;

  v_key := 'release:' || v_hold.operation_key;
  select * into v_entry from public.credit_ledger
   where user_id = p_user_id and operation_key = v_key;
  if found then
    if v_entry.operation_type <> 'release' or v_entry.hold_id <> p_hold_id
       or v_entry.metadata ->> 'reason_code' <> p_reason_code then
      raise exception 'Credit release idempotency key mismatch' using errcode = '22023';
    end if;
    return query select v_wallet.available_credits, v_wallet.reserved_credits, true;
    return;
  end if;

  if v_job.status not in ('failed', 'cancelled', 'expired') then
    raise exception 'Credits can be released only after the generation job is terminal'
      using errcode = '55000';
  end if;
  if v_hold.status <> 'held' then
    raise exception 'Credit hold is already terminal' using errcode = '55000';
  end if;
  if v_wallet.reserved_credits < v_hold.amount then
    raise exception 'Wallet reserved balance is inconsistent' using errcode = '23514';
  end if;

  update public.credit_wallets
     set available_credits = available_credits + v_hold.amount,
         reserved_credits = reserved_credits - v_hold.amount,
         updated_at = now()
   where id = v_wallet.id
   returning * into v_wallet;

  update public.credit_holds
     set status = 'released', released_at = now(), updated_at = now()
   where id = v_hold.id;

  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, v_hold.id, 'release', v_key,
    v_hold.amount, -v_hold.amount,
    v_wallet.available_credits, v_wallet.reserved_credits,
    jsonb_build_object('reason_code', p_reason_code)
  );
  return query select v_wallet.available_credits, v_wallet.reserved_credits, false;
end;
$$;

revoke all on function public.create_credited_generation_job_with_outbox(
  uuid, uuid, uuid, text, text, text, text, text, jsonb, jsonb, bigint
) from public, anon, authenticated;
revoke all on function public.complete_credited_generation_job(uuid, text, text)
  from public, anon, authenticated;
grant execute on function public.create_credited_generation_job_with_outbox(
  uuid, uuid, uuid, text, text, text, text, text, jsonb, jsonb, bigint
) to service_role;
grant execute on function public.complete_credited_generation_job(uuid, text, text)
  to service_role;

comment on function public.create_credited_generation_job_with_outbox(
  uuid, uuid, uuid, text, text, text, text, text, jsonb, jsonb, bigint
) is 'Atomically creates a generation job, outbox event, quote-backed hold, wallet reservation, and reserve ledger entry.';
comment on function public.complete_credited_generation_job(uuid, text, text) is
  'Atomically captures a held credit amount and completes the active leased job; caller must verify the private uploaded asset before invoking.';
comment on function public.release_job_credit_hold(uuid, uuid, text) is
  'Idempotently releases a held amount only after the associated job reaches failed, cancelled, or expired.';
