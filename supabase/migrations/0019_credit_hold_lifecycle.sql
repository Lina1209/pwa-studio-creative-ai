-- PWA Studio: idempotent credit grant, reserve and release primitives.
-- Capture is intentionally deferred until it can be committed atomically with
-- successful generation-job completion and verified asset metadata.

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
declare
  v_wallet public.credit_wallets%rowtype;
  v_entry public.credit_ledger%rowtype;
  v_key text;
begin
  if p_user_id is null or p_amount is null or p_amount <= 0
     or p_amount > 1000000000000
     or p_operation_key is null or length(p_operation_key) not between 8 and 200
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 16384 then
    raise exception 'Invalid credit grant parameters' using errcode = '22023';
  end if;
  v_key := 'grant:' || p_operation_key;

  insert into public.credit_wallets(user_id) values (p_user_id)
  on conflict (user_id) do nothing;

  select * into v_wallet from public.credit_wallets
   where user_id = p_user_id for update;

  select * into v_entry from public.credit_ledger
   where user_id = p_user_id and operation_key = v_key;
  if found then
    if v_entry.operation_type <> 'grant' or v_entry.delta_available <> p_amount
       or v_entry.metadata <> p_metadata then
      raise exception 'Credit grant idempotency key mismatch' using errcode = '22023';
    end if;
    return query select v_wallet.available_credits, v_wallet.reserved_credits, true;
    return;
  end if;

  update public.credit_wallets
     set available_credits = available_credits + p_amount,
         updated_at = now()
   where id = v_wallet.id
   returning * into v_wallet;

  insert into public.credit_ledger(
    user_id, operation_type, operation_key, delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, 'grant', v_key, p_amount, 0,
    v_wallet.available_credits, v_wallet.reserved_credits, p_metadata
  );
  return query select v_wallet.available_credits, v_wallet.reserved_credits, false;
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
  v_ledger_key text;
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
  if v_wallet.available_credits < p_amount then
    raise exception 'Insufficient available credits' using errcode = 'P0001';
  end if;

  update public.credit_wallets
     set available_credits = available_credits - p_amount,
         reserved_credits = reserved_credits + p_amount,
         updated_at = now()
   where id = v_wallet.id
   returning * into v_wallet;

  insert into public.credit_holds(user_id, job_id, amount, quote_snapshot, operation_key)
  values (p_user_id, p_job_id, p_amount, p_quote_snapshot, p_operation_key)
  returning * into v_hold;

  v_ledger_key := 'reserve:' || p_operation_key;
  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    p_user_id, v_hold.id, 'reserve', v_ledger_key,
    -p_amount, p_amount,
    v_wallet.available_credits, v_wallet.reserved_credits,
    jsonb_build_object('job_id', p_job_id, 'quote_snapshot', p_quote_snapshot)
  );
  return query select v_hold.id, v_wallet.available_credits, v_wallet.reserved_credits, false;
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
  v_wallet public.credit_wallets%rowtype;
  v_hold public.credit_holds%rowtype;
  v_entry public.credit_ledger%rowtype;
  v_key text;
begin
  if p_user_id is null or p_hold_id is null
     or p_reason_code is null or p_reason_code !~ '^[a-z0-9_]{3,64}$' then
    raise exception 'Invalid credit hold release parameters' using errcode = '22023';
  end if;

  select * into v_hold from public.credit_holds
   where id = p_hold_id and user_id = p_user_id;
  if not found then raise exception 'Credit hold not found for owner' using errcode = 'P0002'; end if;

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

revoke all on function public.grant_user_credits(uuid,bigint,text,jsonb) from public, anon, authenticated;
revoke all on function public.reserve_job_credits(uuid,uuid,bigint,text,jsonb) from public, anon, authenticated;
revoke all on function public.release_job_credit_hold(uuid,uuid,text) from public, anon, authenticated;
grant execute on function public.grant_user_credits(uuid,bigint,text,jsonb) to service_role;
grant execute on function public.reserve_job_credits(uuid,uuid,bigint,text,jsonb) to service_role;
grant execute on function public.release_job_credit_hold(uuid,uuid,text) to service_role;

comment on function public.grant_user_credits(uuid,bigint,text,jsonb) is
  'Idempotent service-role-only credit grant; use only for audited grants/adjustments.';
comment on function public.reserve_job_credits(uuid,uuid,bigint,text,jsonb) is
  'Idempotent service-role-only hold reservation. Not yet atomic with job/outbox creation.';
comment on function public.release_job_credit_hold(uuid,uuid,text) is
  'Idempotent service-role-only release of a held amount; call only after terminal policy approval.';
