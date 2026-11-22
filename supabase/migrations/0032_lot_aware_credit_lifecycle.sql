-- PWA Studio: source-aware credit lot lifecycle.
-- Grants, FIFO reservations, expiry, capture and release update lots, holds,
-- aggregate wallet projections and the append-only ledger atomically.

-- Expire unreserved credits before a spend admission. The wallet and every
-- affected lot are updated in one transaction; the adjustment ledger is append-only.
create or replace function public.expire_credit_lots_for_user(p_user_id uuid)
returns bigint
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_lot record;
  v_expired bigint := 0;
begin
  if p_user_id is null then
    raise exception 'User is required for credit expiry' using errcode = '22023';
  end if;
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;
  if not found then return 0; end if;

  for v_lot in
    select id, available_credits
      from public.credit_lots
     where user_id = p_user_id
       and available_credits > 0
       and expires_at is not null
       and expires_at <= now()
     order by expires_at, created_at, id
     for update
  loop
    if v_wallet.available_credits < v_lot.available_credits then
      raise exception 'Wallet balance is inconsistent with expired credit lot'
        using errcode = '23514';
    end if;
    update public.credit_lots
       set available_credits = 0, updated_at = now()
     where id = v_lot.id and user_id = p_user_id;

    update public.credit_wallets
       set available_credits = available_credits - v_lot.available_credits,
           updated_at = now()
     where user_id = p_user_id
     returning * into v_wallet;

    insert into public.credit_ledger(
      user_id, operation_type, operation_key,
      delta_available, delta_reserved,
      balance_available_after, balance_reserved_after, metadata
    ) values (
      p_user_id, 'adjustment', 'expire:' || v_lot.id::text,
      -v_lot.available_credits, 0,
      v_wallet.available_credits, v_wallet.reserved_credits,
      jsonb_build_object('reason_code', 'credit_lot_expired', 'lot_id', v_lot.id)
    );
    v_expired := v_expired + v_lot.available_credits;
  end loop;
  return v_expired;
end;
$$;

create or replace function public.allocate_credit_hold_lots(
  p_user_id uuid,
  p_hold_id uuid
)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_hold public.credit_holds%rowtype;
  v_lot record;
  v_remaining bigint;
  v_take bigint;
  v_available_total bigint;
  v_reserved_total bigint;
  v_allocation_total bigint;
begin
  if p_user_id is null or p_hold_id is null then
    raise exception 'Credit hold owner and id are required' using errcode = '22023';
  end if;

  perform public.expire_credit_lots_for_user(p_user_id);
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;
  if not found then
    raise exception 'Credit wallet is missing' using errcode = '23514';
  end if;
  select * into v_hold from public.credit_holds
   where id = p_hold_id and user_id = p_user_id for update;
  if not found or v_hold.status <> 'held' then
    raise exception 'An active credit hold is required for lot allocation'
      using errcode = '55000';
  end if;

  select coalesce(sum(amount), 0) into v_allocation_total
    from public.credit_hold_allocations
   where hold_id = p_hold_id and user_id = p_user_id and status = 'held';
  if v_allocation_total > 0 then
    if v_allocation_total <> v_hold.amount then
      raise exception 'Existing credit hold allocations do not match hold amount'
        using errcode = '23514';
    end if;
    return;
  end if;

  select coalesce(sum(available_credits), 0),
         coalesce(sum(reserved_credits), 0)
    into v_available_total, v_reserved_total
    from public.credit_lots where user_id = p_user_id;
  if v_available_total <> v_wallet.available_credits
     or v_reserved_total <> v_wallet.reserved_credits then
    raise exception 'Credit lot totals do not reconcile with wallet'
      using errcode = '23514';
  end if;
  if v_wallet.available_credits < v_hold.amount then
    raise exception 'Insufficient available credits in unexpired lots'
      using errcode = 'P0001';
  end if;

  v_remaining := v_hold.amount;
  for v_lot in
    select id, available_credits
      from public.credit_lots
     where user_id = p_user_id and available_credits > 0
       and (expires_at is null or expires_at > now())
     order by expires_at asc nulls last, created_at, id
     for update
  loop
    exit when v_remaining = 0;
    v_take := least(v_remaining, v_lot.available_credits);
    update public.credit_lots
       set available_credits = available_credits - v_take,
           reserved_credits = reserved_credits + v_take,
           updated_at = now()
     where id = v_lot.id and user_id = p_user_id;

    insert into public.credit_hold_allocations(user_id, hold_id, lot_id, amount)
    values (p_user_id, p_hold_id, v_lot.id, v_take);
    v_remaining := v_remaining - v_take;
  end loop;

  if v_remaining <> 0 then
    raise exception 'Insufficient unexpired credit lot balance'
      using errcode = 'P0001';
  end if;

  update public.credit_wallets
     set available_credits = available_credits - v_hold.amount,
         reserved_credits = reserved_credits + v_hold.amount,
         updated_at = now()
   where user_id = p_user_id
   returning * into v_wallet;

  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, p_hold_id, 'reserve', 'reserve:' || v_hold.operation_key,
    -v_hold.amount, v_hold.amount,
    v_wallet.available_credits, v_wallet.reserved_credits,
    jsonb_build_object('job_id', v_hold.job_id, 'quote_snapshot', v_hold.quote_snapshot)
  );
end;
$$;

create or replace function public.resolve_credit_hold_lots(
  p_user_id uuid,
  p_hold_id uuid,
  p_action text,
  p_reason_code text default null,
  p_metadata jsonb default '{}'::jsonb
)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_hold public.credit_holds%rowtype;
  v_allocation record;
  v_restored bigint := 0;
  v_forfeited bigint := 0;
  v_new_available bigint;
  v_new_reserved bigint;
begin
  if p_user_id is null or p_hold_id is null
     or p_action not in ('capture', 'release')
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 4096
     or (p_action = 'release' and
         (p_reason_code is null or p_reason_code !~ '^[a-z0-9_]{3,64}
    raise exception 'Invalid credit hold resolution parameters' using errcode = '22023';
  end if;

  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;
  if not found then raise exception 'Credit wallet is missing' using errcode = '23514'; end if;
  select * into v_hold from public.credit_holds
   where id = p_hold_id and user_id = p_user_id for update;
  if not found or v_hold.status <> 'held' then
    raise exception 'Only a held credit reservation can be resolved'
      using errcode = '55000';
  end if;

  if (select coalesce(sum(amount), 0)
        from public.credit_hold_allocations
       where hold_id = p_hold_id and user_id = p_user_id and status = 'held')
       <> v_hold.amount then
    raise exception 'Credit hold allocations are missing or inconsistent'
      using errcode = '23514';
  end if;
  if v_wallet.reserved_credits < v_hold.amount then
    raise exception 'Wallet reserved balance is inconsistent'
      using errcode = '23514';
  end if;

  for v_allocation in
    select a.id as allocation_id, a.lot_id, a.amount, l.expires_at
      from public.credit_hold_allocations a
      join public.credit_lots l on l.id = a.lot_id and l.user_id = a.user_id
     where a.hold_id = p_hold_id and a.user_id = p_user_id and a.status = 'held'
     order by l.expires_at asc nulls last, l.created_at, l.id
     for update of l, a
  loop
    if p_action = 'release' and
       (v_allocation.expires_at is null or v_allocation.expires_at > now()) then
      update public.credit_lots
         set reserved_credits = reserved_credits - v_allocation.amount,
             available_credits = available_credits + v_allocation.amount,
             updated_at = now()
       where id = v_allocation.lot_id and user_id = p_user_id
         and reserved_credits >= v_allocation.amount;
      v_restored := v_restored + v_allocation.amount;
    else
      update public.credit_lots
         set reserved_credits = reserved_credits - v_allocation.amount,
             updated_at = now()
       where id = v_allocation.lot_id and user_id = p_user_id
         and reserved_credits >= v_allocation.amount;
      if p_action = 'release' then
        v_forfeited := v_forfeited + v_allocation.amount;
      end if;
    end if;

    if not found then
      raise exception 'Credit lot reserved balance is inconsistent'
        using errcode = '23514';
    end if;
    update public.credit_hold_allocations
       set status = case when p_action = 'capture' then 'captured' else 'released' end,
           updated_at = now()
     where id = v_allocation.allocation_id;
  end loop;

  update public.credit_wallets
     set available_credits = available_credits + v_restored,
         reserved_credits = reserved_credits - v_hold.amount,
         updated_at = now()
   where user_id = p_user_id
   returning available_credits, reserved_credits
     into v_new_available, v_new_reserved;

  update public.credit_holds
     set status = case when p_action = 'capture' then 'captured' else 'released' end,
         captured_at = case when p_action = 'capture' then now() else null end,
         released_at = case when p_action = 'release' then now() else null end,
         updated_at = now()
   where id = p_hold_id;

  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, p_hold_id,
    case when p_action = 'capture' then 'capture' else 'release' end,
    case when p_action = 'capture'
         then 'capture:' || v_hold.operation_key
         else 'release:' || v_hold.operation_key end,
    v_restored, -v_hold.amount,
    v_new_available, v_new_reserved,
    case when p_action = 'capture'
      then p_metadata || jsonb_build_object(
        'job_id', v_hold.job_id, 'quote_snapshot', v_hold.quote_snapshot
      )
      else jsonb_build_object('reason_code', p_reason_code,
                              'expired_credits_forfeited', v_forfeited)
    end
  );
end;
$$;

create or replace function public.grant_user_credit_lot(
  p_user_id uuid,
  p_amount bigint,
  p_lot_type text,
  p_source_reference text,
  p_idempotency_key text,
  p_expires_at timestamptz default null,
  p_metadata jsonb default '{}'::jsonb
)
returns table(available_credits bigint, reserved_credits bigint, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_lot public.credit_lots%rowtype;
  v_entry public.credit_ledger%rowtype;
  v_ledger_key text;
  v_metadata jsonb;
  v_lot_available_total bigint;
  v_lot_reserved_total bigint;
begin
  if p_user_id is null or p_amount is null or p_amount <= 0
     or p_amount > 1000000000000
     or p_lot_type not in ('free', 'subscription', 'purchased', 'bonus', 'adjustment')
     or p_source_reference is null or length(p_source_reference) not between 8 and 240
     or p_idempotency_key is null or length(p_idempotency_key) not between 8 and 234
     or (p_lot_type in ('free', 'subscription') and p_expires_at is null)
     or (p_expires_at is not null and p_expires_at <= now())
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 16384 then
    raise exception 'Invalid source-separated credit grant parameters' using errcode = '22023';
  end if;
  v_ledger_key := 'grant:' || p_idempotency_key;
  v_metadata := p_metadata || jsonb_build_object(
    'lot_type', p_lot_type, 'source_reference', p_source_reference,
    'expires_at', p_expires_at
  );
  if octet_length(v_metadata::text) > 16384 then
    raise exception 'Credit grant metadata is too large' using errcode = '22023';
  end if;

  perform public.expire_credit_lots_for_user(p_user_id);
  insert into public.credit_wallets(user_id) values (p_user_id)
  on conflict (user_id) do nothing;
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;
  select coalesce(sum(available_credits), 0),
         coalesce(sum(reserved_credits), 0)
    into v_lot_available_total, v_lot_reserved_total
    from public.credit_lots where user_id = p_user_id;
  if v_lot_available_total <> v_wallet.available_credits
     or v_lot_reserved_total <> v_wallet.reserved_credits then
    raise exception 'Credit lot totals do not reconcile with wallet before grant'
      using errcode = '23514';
  end if;

  select * into v_lot from public.credit_lots
   where user_id = p_user_id and idempotency_key = p_idempotency_key;
  if found then
    if v_lot.granted_credits <> p_amount
       or v_lot.lot_type <> p_lot_type
       or v_lot.source_reference <> p_source_reference
       or v_lot.expires_at is distinct from p_expires_at then
      raise exception 'Credit lot idempotency key mismatch' using errcode = '22023';
    end if;
    select * into v_entry from public.credit_ledger
     where user_id = p_user_id and operation_key = v_ledger_key;
    if not found or v_entry.operation_type <> 'grant'
       or v_entry.delta_available <> p_amount or v_entry.metadata <> v_metadata then
      raise exception 'Credit lot grant ledger is missing or inconsistent'
        using errcode = '23514';
    end if;
    return query select v_wallet.available_credits, v_wallet.reserved_credits, true;
    return;
  end if;

  update public.credit_wallets as wallet
     set available_credits = wallet.available_credits + p_amount,
         updated_at = now()
   where wallet.user_id = p_user_id
   returning wallet.* into v_wallet;

  insert into public.credit_lots(
    user_id, lot_type, source_reference, idempotency_key,
    granted_credits, available_credits, expires_at
  ) values (
    p_user_id, p_lot_type, p_source_reference, p_idempotency_key,
    p_amount, p_amount, p_expires_at
  ) returning * into v_lot;

  insert into public.credit_ledger(
    user_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, 'grant', v_ledger_key,
    p_amount, 0,
    v_wallet.available_credits, v_wallet.reserved_credits, v_metadata
  );
  return query select v_wallet.available_credits, v_wallet.reserved_credits, false;
end;
$$;


create or replace function public.grant_user_credits(
  p_user_id uuid,
  p_amount bigint,
  p_operation_key text,
  p_metadata jsonb default '{}'::jsonb
)
returns table(available_credits bigint, reserved_credits bigint, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  return query
    select g.available_credits, g.reserved_credits, g.replayed
      from public.grant_user_credit_lot(
        p_user_id, p_amount, 'adjustment',
        'legacy-grant:' || p_operation_key, p_operation_key, null, p_metadata
      ) g;
end;
$$;
create or replace function public.reserve_job_credits(
  p_user_id uuid,
  p_job_id uuid,
  p_amount bigint,
  p_operation_key text,
  p_quote_snapshot jsonb
)
returns table(hold_id uuid, available_credits bigint, reserved_credits bigint, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_hold public.credit_holds%rowtype;
  v_job public.generation_jobs%rowtype;
  v_entry public.credit_ledger%rowtype;
begin
  if p_user_id is null or p_job_id is null or p_amount is null or p_amount <= 0
     or p_amount > 1000000000000
     or p_operation_key is null or length(p_operation_key) not between 8 and 200
     or p_quote_snapshot is null or jsonb_typeof(p_quote_snapshot) <> 'object'
     or octet_length(p_quote_snapshot::text) > 16384 then
    raise exception 'Invalid credit reservation parameters' using errcode = '22023';
  end if;

  select * into v_job from public.generation_jobs
   where id = p_job_id and user_id = p_user_id for update;
  if not found then
    raise exception 'Generation job not found for owner' using errcode = 'P0002';
  end if;
  if v_job.status not in ('queued', 'running', 'retry_wait') then
    raise exception 'Generation job is not eligible for reservation' using errcode = '55000';
  end if;

  insert into public.credit_wallets(user_id) values (p_user_id)
  on conflict (user_id) do nothing;
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;

  select * into v_hold from public.credit_holds
   where user_id = p_user_id and operation_key = p_operation_key;
  if found then
    if v_hold.job_id <> p_job_id or v_hold.amount <> p_amount
       or v_hold.quote_snapshot <> p_quote_snapshot then
      raise exception 'Credit reservation idempotency key mismatch' using errcode = '22023';
    end if;
    return query select v_hold.id, v_wallet.available_credits, v_wallet.reserved_credits, true;
    return;
  end if;

  if exists (select 1 from public.credit_holds where job_id = p_job_id) then
    raise exception 'Generation job already has a credit hold' using errcode = '23505';
  end if;
  insert into public.credit_holds(user_id, job_id, amount, quote_snapshot, operation_key)
  values (p_user_id, p_job_id, p_amount, p_quote_snapshot, p_operation_key)
  returning * into v_hold;

  perform public.allocate_credit_hold_lots(p_user_id, v_hold.id);
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id;
  return query select v_hold.id, v_wallet.available_credits, v_wallet.reserved_credits, false;
end;
$$;
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

    select hold.* into v_hold from public.credit_holds as hold
     where hold.user_id = p_user_id and hold.job_id = v_existing.id
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

  insert into public.credit_holds(
    user_id, job_id, amount, quote_snapshot, operation_key
  ) values (
    p_user_id, v_job_id, p_credit_amount, p_quote_snapshot, p_idempotency_key
  ) returning * into v_hold;

  perform public.allocate_credit_hold_lots(p_user_id, v_hold.id);
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id;

  return query select v_job_id, v_event_id, v_hold.id,
    v_wallet.available_credits, v_wallet.reserved_credits, true, false;
end;
$$;
create or replace function public.complete_credited_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_result_storage_path text,
  p_result_sha256 text
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
     or position('..' in p_result_storage_path) > 0
     or p_result_sha256 is null or p_result_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'Invalid credited completion parameters' using errcode = '22023';
  end if;

  select * into v_job from public.generation_jobs
   where id = p_job_id for update;
  if not found then raise exception 'Generation job not found' using errcode = 'P0002'; end if;

  -- A repeated completion is accepted only when the exact result path and
  -- captured hold are already recorded; it never mutates balances a second time.
  if v_job.status = 'succeeded' then
    if v_job.result_storage_path is distinct from p_result_storage_path
       or v_job.result_sha256 is distinct from p_result_sha256 then
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

  perform public.resolve_credit_hold_lots(
    v_job.user_id, v_hold.id, 'capture', null,
    jsonb_build_object(
      'result_storage_path', p_result_storage_path,
      'result_sha256', p_result_sha256
    )
  );
  select * into v_wallet from public.credit_wallets
   where user_id = v_job.user_id;

  update public.generation_jobs
     set status = 'succeeded',
         result_storage_path = p_result_storage_path,
         result_sha256 = p_result_sha256,
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         updated_at = now()
   where id = p_job_id;

  return query select true, false, v_wallet.available_credits, v_wallet.reserved_credits;
end;
$$;
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
  perform public.resolve_credit_hold_lots(
    p_user_id, v_hold.id, 'release', p_reason_code
  );
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id;
  return query select v_wallet.available_credits, v_wallet.reserved_credits, false;
end;
$$;

-- Only the trusted backend service role may invoke these financial operations.
revoke all on function public.expire_credit_lots_for_user(uuid) from public, anon, authenticated;
revoke all on function public.allocate_credit_hold_lots(uuid,uuid) from public, anon, authenticated;
revoke all on function public.resolve_credit_hold_lots(uuid,uuid,text,text,jsonb) from public, anon, authenticated;
revoke all on function public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamptz,jsonb)
  from public, anon, authenticated;
revoke all on function public.grant_user_credits(uuid,bigint,text,jsonb) from public, anon, authenticated;
revoke all on function public.reserve_job_credits(uuid,uuid,bigint,text,jsonb) from public, anon, authenticated;
revoke all on function public.release_job_credit_hold(uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.create_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) from public, anon, authenticated;
revoke all on function public.complete_credited_generation_job(uuid,text,text,text)
  from public, anon, authenticated;

grant execute on function public.expire_credit_lots_for_user(uuid) to service_role;
grant execute on function public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamptz,jsonb)
  to service_role;
grant execute on function public.grant_user_credits(uuid,bigint,text,jsonb) to service_role;
grant execute on function public.reserve_job_credits(uuid,uuid,bigint,text,jsonb) to service_role;
grant execute on function public.release_job_credit_hold(uuid,uuid,text) to service_role;
grant execute on function public.create_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) to service_role;
grant execute on function public.complete_credited_generation_job(uuid,text,text,text)
  to service_role;

comment on function public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamptz,jsonb) is
  'Idempotently creates one source-typed credit lot; caller must be trusted server code after verifying the grant source.';
comment on function public.expire_credit_lots_for_user(uuid) is
  'Expires available credits and writes compensating adjustment ledger entries; invoke from trusted scheduled maintenance.';
comment on function public.allocate_credit_hold_lots(uuid,uuid) is
  'Atomically allocates a quote-backed hold from unexpired lots in earliest-expiry-first order.';
comment on function public.resolve_credit_hold_lots(uuid,uuid,text,text) is
  'Captures or releases exact lot allocations; expired allocations are forfeited on release, never resurrected.';


-- Read-only snapshot reports only currently spendable credits. Expired
-- available amounts remain in storage until the expiry sweep, but are never
-- presented as spendable and are removed atomically before any new reservation.
create or replace function public.get_credit_wallet_snapshot(
  p_user_id uuid,
  p_history_limit integer default 50
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_holds jsonb;
  v_ledger jsonb;
  v_lots jsonb;
  v_allocations jsonb;
  v_spendable bigint;
begin
  if p_user_id is null or p_history_limit is null
     or p_history_limit not between 1 and 100 then
    raise exception 'Invalid credit wallet snapshot request'
      using errcode = '22023';
  end if;
  select * into v_wallet from public.credit_wallets where user_id = p_user_id;

  select coalesce(sum(case when expires_at is null or expires_at > now()
                           then available_credits else 0 end), 0)
    into v_spendable
    from public.credit_lots where user_id = p_user_id;

  select coalesce(jsonb_agg(to_jsonb(h) order by h.created_at desc), '[]'::jsonb)
    into v_holds
    from (
      select id, job_id, amount, status, created_at
        from public.credit_holds where user_id = p_user_id and status = 'held'
       order by created_at desc limit 20
    ) h;

  select coalesce(jsonb_agg(to_jsonb(l) order by l.created_at desc, l.id desc), '[]'::jsonb)
    into v_ledger
    from (
      select id, operation_type, operation_key,
             delta_available, delta_reserved,
             balance_available_after, balance_reserved_after, created_at
        from public.credit_ledger where user_id = p_user_id
       order by created_at desc, id desc limit p_history_limit
    ) l;

  select coalesce(jsonb_agg(to_jsonb(lot) order by lot.expires_at asc nulls last,
                            lot.created_at, lot.id), '[]'::jsonb)
    into v_lots
    from (
      select id, lot_type, granted_credits,
             case when expires_at is not null and expires_at <= now()
                  then 0 else available_credits end as available_credits,
             reserved_credits, expires_at, created_at
        from public.credit_lots where user_id = p_user_id
       order by expires_at asc nulls last, created_at, id limit 100
    ) lot;

  select coalesce(jsonb_agg(to_jsonb(a) order by a.created_at, a.id), '[]'::jsonb)
    into v_allocations
    from (
      select id, hold_id, lot_id, amount, status, created_at
        from public.credit_hold_allocations
       where user_id = p_user_id and status = 'held'
       order by created_at, id limit 100
    ) a;

  return jsonb_build_object(
    'user_id', p_user_id,
    'currency_unit', 'credit',
    'available_credits', v_spendable,
    'reserved_credits', coalesce(v_wallet.reserved_credits, 0),
    'holds', v_holds, 'ledger', v_ledger,
    'lots', v_lots, 'allocations', v_allocations
  );
end;
$$;

revoke all on function public.get_credit_wallet_snapshot(uuid, integer)
  from public, anon, authenticated;
grant execute on function public.get_credit_wallet_snapshot(uuid, integer)
  to service_role;

)) then
    raise exception 'Invalid credit hold resolution parameters' using errcode = '22023';
  end if;

  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;
  if not found then raise exception 'Credit wallet is missing' using errcode = '23514'; end if;
  select * into v_hold from public.credit_holds
   where id = p_hold_id and user_id = p_user_id for update;
  if not found or v_hold.status <> 'held' then
    raise exception 'Only a held credit reservation can be resolved'
      using errcode = '55000';
  end if;

  if (select coalesce(sum(amount), 0)
        from public.credit_hold_allocations
       where hold_id = p_hold_id and user_id = p_user_id and status = 'held')
       <> v_hold.amount then
    raise exception 'Credit hold allocations are missing or inconsistent'
      using errcode = '23514';
  end if;
  if v_wallet.reserved_credits < v_hold.amount then
    raise exception 'Wallet reserved balance is inconsistent'
      using errcode = '23514';
  end if;

  for v_allocation in
    select a.id as allocation_id, a.lot_id, a.amount, l.expires_at
      from public.credit_hold_allocations a
      join public.credit_lots l on l.id = a.lot_id and l.user_id = a.user_id
     where a.hold_id = p_hold_id and a.user_id = p_user_id and a.status = 'held'
     order by l.expires_at asc nulls last, l.created_at, l.id
     for update of l, a
  loop
    if p_action = 'release' and
       (v_allocation.expires_at is null or v_allocation.expires_at > now()) then
      update public.credit_lots
         set reserved_credits = reserved_credits - v_allocation.amount,
             available_credits = available_credits + v_allocation.amount,
             updated_at = now()
       where id = v_allocation.lot_id and user_id = p_user_id
         and reserved_credits >= v_allocation.amount;
      v_restored := v_restored + v_allocation.amount;
    else
      update public.credit_lots
         set reserved_credits = reserved_credits - v_allocation.amount,
             updated_at = now()
       where id = v_allocation.lot_id and user_id = p_user_id
         and reserved_credits >= v_allocation.amount;
      if p_action = 'release' then
        v_forfeited := v_forfeited + v_allocation.amount;
      end if;
    end if;

    if not found then
      raise exception 'Credit lot reserved balance is inconsistent'
        using errcode = '23514';
    end if;
    update public.credit_hold_allocations
       set status = case when p_action = 'capture' then 'captured' else 'released' end,
           updated_at = now()
     where id = v_allocation.allocation_id;
  end loop;

  update public.credit_wallets
     set available_credits = available_credits + v_restored,
         reserved_credits = reserved_credits - v_hold.amount,
         updated_at = now()
   where user_id = p_user_id
   returning available_credits, reserved_credits
     into v_new_available, v_new_reserved;

  update public.credit_holds
     set status = case when p_action = 'capture' then 'captured' else 'released' end,
         captured_at = case when p_action = 'capture' then now() else null end,
         released_at = case when p_action = 'release' then now() else null end,
         updated_at = now()
   where id = p_hold_id;

  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, p_hold_id,
    case when p_action = 'capture' then 'capture' else 'release' end,
    case when p_action = 'capture'
         then 'capture:' || v_hold.operation_key
         else 'release:' || v_hold.operation_key end,
    v_restored, -v_hold.amount,
    v_new_available, v_new_reserved,
    case when p_action = 'capture'
      then jsonb_build_object('job_id', v_hold.job_id, 'quote_snapshot', v_hold.quote_snapshot)
      else jsonb_build_object('reason_code', p_reason_code,
                              'expired_credits_forfeited', v_forfeited)
    end
  );
end;
$$;

create or replace function public.grant_user_credit_lot(
  p_user_id uuid,
  p_amount bigint,
  p_lot_type text,
  p_source_reference text,
  p_idempotency_key text,
  p_expires_at timestamptz default null,
  p_metadata jsonb default '{}'::jsonb
)
returns table(available_credits bigint, reserved_credits bigint, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_lot public.credit_lots%rowtype;
  v_entry public.credit_ledger%rowtype;
  v_ledger_key text;
  v_metadata jsonb;
  v_lot_available_total bigint;
  v_lot_reserved_total bigint;
begin
  if p_user_id is null or p_amount is null or p_amount <= 0
     or p_amount > 1000000000000
     or p_lot_type not in ('free', 'subscription', 'purchased', 'bonus', 'adjustment')
     or p_source_reference is null or length(p_source_reference) not between 8 and 240
     or p_idempotency_key is null or length(p_idempotency_key) not between 8 and 234
     or (p_expires_at is not null and p_expires_at <= now())
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 16384 then
    raise exception 'Invalid source-separated credit grant parameters' using errcode = '22023';
  end if;
  v_ledger_key := 'grant:' || p_idempotency_key;
  v_metadata := p_metadata || jsonb_build_object(
    'lot_type', p_lot_type, 'source_reference', p_source_reference,
    'expires_at', p_expires_at
  );
  if octet_length(v_metadata::text) > 16384 then
    raise exception 'Credit grant metadata is too large' using errcode = '22023';
  end if;

  perform public.expire_credit_lots_for_user(p_user_id);
  insert into public.credit_wallets(user_id) values (p_user_id)
  on conflict (user_id) do nothing;
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;
  select coalesce(sum(available_credits), 0),
         coalesce(sum(reserved_credits), 0)
    into v_lot_available_total, v_lot_reserved_total
    from public.credit_lots where user_id = p_user_id;
  if v_lot_available_total <> v_wallet.available_credits
     or v_lot_reserved_total <> v_wallet.reserved_credits then
    raise exception 'Credit lot totals do not reconcile with wallet before grant'
      using errcode = '23514';
  end if;

  select * into v_lot from public.credit_lots
   where user_id = p_user_id and idempotency_key = p_idempotency_key;
  if found then
    if v_lot.granted_credits <> p_amount
       or v_lot.lot_type <> p_lot_type
       or v_lot.source_reference <> p_source_reference
       or v_lot.expires_at is distinct from p_expires_at then
      raise exception 'Credit lot idempotency key mismatch' using errcode = '22023';
    end if;
    select * into v_entry from public.credit_ledger
     where user_id = p_user_id and operation_key = v_ledger_key;
    if not found or v_entry.operation_type <> 'grant'
       or v_entry.delta_available <> p_amount or v_entry.metadata <> v_metadata then
      raise exception 'Credit lot grant ledger is missing or inconsistent'
        using errcode = '23514';
    end if;
    return query select v_wallet.available_credits, v_wallet.reserved_credits, true;
    return;
  end if;

  update public.credit_wallets as wallet
     set available_credits = wallet.available_credits + p_amount,
         updated_at = now()
   where wallet.user_id = p_user_id
   returning wallet.* into v_wallet;

  insert into public.credit_lots(
    user_id, lot_type, source_reference, idempotency_key,
    granted_credits, available_credits, expires_at
  ) values (
    p_user_id, p_lot_type, p_source_reference, p_idempotency_key,
    p_amount, p_amount, p_expires_at
  ) returning * into v_lot;

  insert into public.credit_ledger(
    user_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, 'grant', v_ledger_key,
    p_amount, 0,
    v_wallet.available_credits, v_wallet.reserved_credits, v_metadata
  );
  return query select v_wallet.available_credits, v_wallet.reserved_credits, false;
end;
$$;


create or replace function public.grant_user_credits(
  p_user_id uuid,
  p_amount bigint,
  p_operation_key text,
  p_metadata jsonb default '{}'::jsonb
)
returns table(available_credits bigint, reserved_credits bigint, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  return query
    select g.available_credits, g.reserved_credits, g.replayed
      from public.grant_user_credit_lot(
        p_user_id, p_amount, 'adjustment',
        'legacy-grant:' || p_operation_key, p_operation_key, null, p_metadata
      ) g;
end;
$$;
create or replace function public.reserve_job_credits(
  p_user_id uuid,
  p_job_id uuid,
  p_amount bigint,
  p_operation_key text,
  p_quote_snapshot jsonb
)
returns table(hold_id uuid, available_credits bigint, reserved_credits bigint, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_hold public.credit_holds%rowtype;
  v_job public.generation_jobs%rowtype;
  v_entry public.credit_ledger%rowtype;
begin
  if p_user_id is null or p_job_id is null or p_amount is null or p_amount <= 0
     or p_amount > 1000000000000
     or p_operation_key is null or length(p_operation_key) not between 8 and 200
     or p_quote_snapshot is null or jsonb_typeof(p_quote_snapshot) <> 'object'
     or octet_length(p_quote_snapshot::text) > 16384 then
    raise exception 'Invalid credit reservation parameters' using errcode = '22023';
  end if;

  select * into v_job from public.generation_jobs
   where id = p_job_id and user_id = p_user_id for update;
  if not found then
    raise exception 'Generation job not found for owner' using errcode = 'P0002';
  end if;
  if v_job.status not in ('queued', 'running', 'retry_wait') then
    raise exception 'Generation job is not eligible for reservation' using errcode = '55000';
  end if;

  insert into public.credit_wallets(user_id) values (p_user_id)
  on conflict (user_id) do nothing;
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;

  select * into v_hold from public.credit_holds
   where user_id = p_user_id and operation_key = p_operation_key;
  if found then
    if v_hold.job_id <> p_job_id or v_hold.amount <> p_amount
       or v_hold.quote_snapshot <> p_quote_snapshot then
      raise exception 'Credit reservation idempotency key mismatch' using errcode = '22023';
    end if;
    return query select v_hold.id, v_wallet.available_credits, v_wallet.reserved_credits, true;
    return;
  end if;

  if exists (select 1 from public.credit_holds where job_id = p_job_id) then
    raise exception 'Generation job already has a credit hold' using errcode = '23505';
  end if;
  insert into public.credit_holds(user_id, job_id, amount, quote_snapshot, operation_key)
  values (p_user_id, p_job_id, p_amount, p_quote_snapshot, p_operation_key)
  returning * into v_hold;

  perform public.allocate_credit_hold_lots(p_user_id, v_hold.id);
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id;
  return query select v_hold.id, v_wallet.available_credits, v_wallet.reserved_credits, false;
end;
$$;
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

    select hold.* into v_hold from public.credit_holds as hold
     where hold.user_id = p_user_id and hold.job_id = v_existing.id
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

  insert into public.credit_holds(
    user_id, job_id, amount, quote_snapshot, operation_key
  ) values (
    p_user_id, v_job_id, p_credit_amount, p_quote_snapshot, p_idempotency_key
  ) returning * into v_hold;

  perform public.allocate_credit_hold_lots(p_user_id, v_hold.id);
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id;

  return query select v_job_id, v_event_id, v_hold.id,
    v_wallet.available_credits, v_wallet.reserved_credits, true, false;
end;
$$;
create or replace function public.complete_credited_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_result_storage_path text,
  p_result_sha256 text
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
     or position('..' in p_result_storage_path) > 0
     or p_result_sha256 is null or p_result_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'Invalid credited completion parameters' using errcode = '22023';
  end if;

  select * into v_job from public.generation_jobs
   where id = p_job_id for update;
  if not found then raise exception 'Generation job not found' using errcode = 'P0002'; end if;

  -- A repeated completion is accepted only when the exact result path and
  -- captured hold are already recorded; it never mutates balances a second time.
  if v_job.status = 'succeeded' then
    if v_job.result_storage_path is distinct from p_result_storage_path
       or v_job.result_sha256 is distinct from p_result_sha256 then
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

  perform public.resolve_credit_hold_lots(
    v_job.user_id, v_hold.id, 'capture', null
  );
  select * into v_wallet from public.credit_wallets
   where user_id = v_job.user_id;

  update public.generation_jobs
     set status = 'succeeded',
         result_storage_path = p_result_storage_path,
         result_sha256 = p_result_sha256,
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         updated_at = now()
   where id = p_job_id;

  return query select true, false, v_wallet.available_credits, v_wallet.reserved_credits;
end;
$$;
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
  perform public.resolve_credit_hold_lots(
    p_user_id, v_hold.id, 'release', p_reason_code
  );
  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id;
  return query select v_wallet.available_credits, v_wallet.reserved_credits, false;
end;
$$;

-- Only the trusted backend service role may invoke these financial operations.
revoke all on function public.expire_credit_lots_for_user(uuid) from public, anon, authenticated;
revoke all on function public.allocate_credit_hold_lots(uuid,uuid) from public, anon, authenticated;
revoke all on function public.resolve_credit_hold_lots(uuid,uuid,text,text) from public, anon, authenticated;
revoke all on function public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamptz,jsonb)
  from public, anon, authenticated;
revoke all on function public.grant_user_credits(uuid,bigint,text,jsonb) from public, anon, authenticated;
revoke all on function public.reserve_job_credits(uuid,uuid,bigint,text,jsonb) from public, anon, authenticated;
revoke all on function public.release_job_credit_hold(uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.create_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) from public, anon, authenticated;
revoke all on function public.complete_credited_generation_job(uuid,text,text,text)
  from public, anon, authenticated;

grant execute on function public.expire_credit_lots_for_user(uuid) to service_role;
grant execute on function public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamptz,jsonb)
  to service_role;
grant execute on function public.grant_user_credits(uuid,bigint,text,jsonb) to service_role;
grant execute on function public.reserve_job_credits(uuid,uuid,bigint,text,jsonb) to service_role;
grant execute on function public.release_job_credit_hold(uuid,uuid,text) to service_role;
grant execute on function public.create_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) to service_role;
grant execute on function public.complete_credited_generation_job(uuid,text,text,text)
  to service_role;

comment on function public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamptz,jsonb) is
  'Idempotently creates one source-typed credit lot; caller must be trusted server code after verifying the grant source.';
comment on function public.expire_credit_lots_for_user(uuid) is
  'Expires available credits and writes compensating adjustment ledger entries; invoke from trusted scheduled maintenance.';
comment on function public.allocate_credit_hold_lots(uuid,uuid) is
  'Atomically allocates a quote-backed hold from unexpired lots in earliest-expiry-first order.';
comment on function public.resolve_credit_hold_lots(uuid,uuid,text,text) is
  'Captures or releases exact lot allocations; expired allocations are forfeited on release, never resurrected.';


-- Read-only snapshot reports only currently spendable credits. Expired
-- available amounts remain in storage until the expiry sweep, but are never
-- presented as spendable and are removed atomically before any new reservation.
create or replace function public.get_credit_wallet_snapshot(
  p_user_id uuid,
  p_history_limit integer default 50
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_holds jsonb;
  v_ledger jsonb;
  v_lots jsonb;
  v_allocations jsonb;
  v_spendable bigint;
begin
  if p_user_id is null or p_history_limit is null
     or p_history_limit not between 1 and 100 then
    raise exception 'Invalid credit wallet snapshot request'
      using errcode = '22023';
  end if;
  select * into v_wallet from public.credit_wallets where user_id = p_user_id;

  select coalesce(sum(case when expires_at is null or expires_at > now()
                           then available_credits else 0 end), 0)
    into v_spendable
    from public.credit_lots where user_id = p_user_id;

  select coalesce(jsonb_agg(to_jsonb(h) order by h.created_at desc), '[]'::jsonb)
    into v_holds
    from (
      select id, job_id, amount, status, created_at
        from public.credit_holds where user_id = p_user_id and status = 'held'
       order by created_at desc limit 20
    ) h;

  select coalesce(jsonb_agg(to_jsonb(l) order by l.created_at desc, l.id desc), '[]'::jsonb)
    into v_ledger
    from (
      select id, operation_type, operation_key,
             delta_available, delta_reserved,
             balance_available_after, balance_reserved_after, created_at
        from public.credit_ledger where user_id = p_user_id
       order by created_at desc, id desc limit p_history_limit
    ) l;

  select coalesce(jsonb_agg(to_jsonb(lot) order by lot.expires_at asc nulls last,
                            lot.created_at, lot.id), '[]'::jsonb)
    into v_lots
    from (
      select id, lot_type, granted_credits,
             case when expires_at is not null and expires_at <= now()
                  then 0 else available_credits end as available_credits,
             reserved_credits, expires_at, created_at
        from public.credit_lots where user_id = p_user_id
       order by expires_at asc nulls last, created_at, id limit 100
    ) lot;

  select coalesce(jsonb_agg(to_jsonb(a) order by a.created_at, a.id), '[]'::jsonb)
    into v_allocations
    from (
      select id, hold_id, lot_id, amount, status, created_at
        from public.credit_hold_allocations
       where user_id = p_user_id and status = 'held'
       order by created_at, id limit 100
    ) a;

  return jsonb_build_object(
    'user_id', p_user_id,
    'currency_unit', 'credit',
    'available_credits', v_spendable,
    'reserved_credits', coalesce(v_wallet.reserved_credits, 0),
    'holds', v_holds, 'ledger', v_ledger,
    'lots', v_lots, 'allocations', v_allocations
  );
end;
$$;

revoke all on function public.get_credit_wallet_snapshot(uuid, integer)
  from public, anon, authenticated;
grant execute on function public.get_credit_wallet_snapshot(uuid, integer)
  to service_role;

