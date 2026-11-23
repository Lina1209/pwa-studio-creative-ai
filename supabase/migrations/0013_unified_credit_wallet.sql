-- PWA Studio unified credit wallet foundation.
-- Source-only until reconciled with the live Supabase migration ledger and schema.
-- All balance mutations happen inside these trusted, atomic RPCs.

create table if not exists public.credit_wallets (
  user_id uuid primary key references auth.users(id) on delete cascade,
  available_credits bigint not null default 0 check (available_credits >= 0),
  reserved_credits bigint not null default 0 check (reserved_credits >= 0),
  updated_at timestamptz not null default now()
);

create table if not exists public.credit_reservations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key text not null check (length(idempotency_key) between 8 and 160),
  operation_code text not null check (length(operation_code) between 1 and 80),
  pricing_version integer not null check (pricing_version > 0),
  reserved_credits bigint not null check (reserved_credits > 0),
  captured_credits bigint check (captured_credits is null or captured_credits >= 0),
  status text not null default 'reserved'
    check (status in ('reserved', 'settled', 'released', 'reconciliation_required')),
  provider_request_reference text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, idempotency_key)
);

create table if not exists public.credit_ledger (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  event_type text not null check (event_type in
    ('grant', 'reserve', 'capture', 'release', 'adjustment')),
  available_delta bigint not null default 0,
  reserved_delta bigint not null default 0,
  reservation_id uuid references public.credit_reservations(id),
  source text not null,
  source_reference text,
  operation_code text,
  pricing_version integer,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists credit_ledger_grant_reference_uidx
  on public.credit_ledger(user_id, source, source_reference)
  where event_type = 'grant' and source_reference is not null;
create index if not exists credit_ledger_user_created_idx
  on public.credit_ledger(user_id, created_at desc);
create index if not exists credit_reservations_user_created_idx
  on public.credit_reservations(user_id, created_at desc);

alter table public.credit_wallets enable row level security;
alter table public.credit_reservations enable row level security;
alter table public.credit_ledger enable row level security;
revoke all on public.credit_wallets, public.credit_reservations, public.credit_ledger
  from anon, authenticated;
grant select, insert, update, delete on public.credit_wallets,
  public.credit_reservations, public.credit_ledger to service_role;
grant usage, select on sequence public.credit_ledger_id_seq to service_role;

create or replace function public.grant_user_credits(
  p_user_id uuid,
  p_amount bigint,
  p_source text,
  p_source_reference text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_existing public.credit_ledger%rowtype;
begin
  if p_user_id is null or p_amount <= 0 or p_amount > 100000000
     or p_source is null or length(p_source) not between 1 and 80
     or p_source_reference is null or length(p_source_reference) not between 1 and 160 then
    raise exception 'Invalid credit grant parameters';
  end if;

  insert into public.credit_wallets(user_id, available_credits)
  values (p_user_id, 0)
  on conflict (user_id) do nothing;
  select * into v_wallet from public.credit_wallets where user_id = p_user_id for update;

  select * into v_existing from public.credit_ledger
   where user_id = p_user_id and event_type = 'grant'
     and source = p_source and source_reference = p_source_reference;
  if found then
    return jsonb_build_object('status', 'already_granted',
      'available_credits', v_wallet.available_credits,
      'reserved_credits', v_wallet.reserved_credits);
  end if;

  update public.credit_wallets
    set available_credits = available_credits + p_amount, updated_at = now()
    where user_id = p_user_id
    returning * into v_wallet;

  insert into public.credit_ledger(user_id, event_type, available_delta,
    source, source_reference)
  values (p_user_id, 'grant', p_amount, p_source, p_source_reference);

  return jsonb_build_object('status', 'granted',
    'available_credits', v_wallet.available_credits,
    'reserved_credits', v_wallet.reserved_credits);
end;
$$;

create or replace function public.reserve_user_credits(
  p_user_id uuid,
  p_idempotency_key text,
  p_operation_code text,
  p_pricing_version integer,
  p_amount bigint
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_reservation public.credit_reservations%rowtype;
begin
  if p_user_id is null or p_idempotency_key is null
     or length(p_idempotency_key) not between 8 and 160
     or p_operation_code is null or length(p_operation_code) not between 1 and 80
     or p_pricing_version <= 0 or p_amount <= 0 or p_amount > 100000000 then
    raise exception 'Invalid credit reservation parameters';
  end if;

  select * into v_wallet from public.credit_wallets where user_id = p_user_id for update;
  if not found then
    return jsonb_build_object('status', 'insufficient_credits');
  end if;

  -- Locking the per-user wallet serializes reservations and grants; recheck
  -- idempotency after the lock so concurrent retries cannot reserve twice.
  select * into v_reservation from public.credit_reservations
   where user_id = p_user_id and idempotency_key = p_idempotency_key
   for update;
  if found then
    return jsonb_build_object('status', v_reservation.status,
      'reservation_id', v_reservation.id,
      'reserved_credits', v_reservation.reserved_credits,
      'captured_credits', v_reservation.captured_credits,
      'idempotent_replay', true);
  end if;

  if v_wallet.available_credits < p_amount then
    return jsonb_build_object('status', 'insufficient_credits');
  end if;

  insert into public.credit_reservations(user_id, idempotency_key, operation_code,
    pricing_version, reserved_credits)
  values (p_user_id, p_idempotency_key, p_operation_code, p_pricing_version, p_amount)
  returning * into v_reservation;

  update public.credit_wallets
    set available_credits = available_credits - p_amount,
        reserved_credits = reserved_credits + p_amount,
        updated_at = now()
    where user_id = p_user_id
    returning * into v_wallet;

  insert into public.credit_ledger(user_id, event_type, available_delta,
    reserved_delta, reservation_id, source, operation_code, pricing_version)
  values (p_user_id, 'reserve', -p_amount, p_amount, v_reservation.id,
    'operation', p_operation_code, p_pricing_version);

  return jsonb_build_object('status', 'reserved',
    'reservation_id', v_reservation.id,
    'reserved_credits', v_reservation.reserved_credits,
    'available_credits', v_wallet.available_credits,
    'reserved_balance', v_wallet.reserved_credits,
    'idempotent_replay', false);
end;
$$;

create or replace function public.settle_user_credit_reservation(
  p_user_id uuid,
  p_reservation_id uuid,
  p_capture_amount bigint
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_reservation public.credit_reservations%rowtype;
  v_wallet public.credit_wallets%rowtype;
  v_refund bigint;
begin
  if p_user_id is null or p_reservation_id is null or p_capture_amount < 0 then
    raise exception 'Invalid credit settlement parameters';
  end if;

  select * into v_reservation from public.credit_reservations
   where id = p_reservation_id and user_id = p_user_id for update;
  if not found then raise exception 'Credit reservation not found'; end if;

  if v_reservation.status = 'settled' then
    return jsonb_build_object('status', 'already_settled',
      'captured_credits', v_reservation.captured_credits);
  end if;
  if v_reservation.status <> 'reserved' or p_capture_amount > v_reservation.reserved_credits then
    raise exception 'Reservation cannot be settled with requested amount';
  end if;

  select * into v_wallet from public.credit_wallets where user_id = p_user_id for update;
  v_refund := v_reservation.reserved_credits - p_capture_amount;

  update public.credit_wallets
    set available_credits = available_credits + v_refund,
        reserved_credits = reserved_credits - v_reservation.reserved_credits,
        updated_at = now()
    where user_id = p_user_id
    returning * into v_wallet;

  update public.credit_reservations
    set status = 'settled', captured_credits = p_capture_amount, updated_at = now()
    where id = p_reservation_id returning * into v_reservation;

  insert into public.credit_ledger(user_id, event_type, available_delta,
    reserved_delta, reservation_id, source, operation_code, pricing_version)
  values (p_user_id, 'capture', v_refund, -v_reservation.reserved_credits,
    p_reservation_id, 'operation', v_reservation.operation_code, v_reservation.pricing_version);

  return jsonb_build_object('status', 'settled',
    'captured_credits', p_capture_amount,
    'refunded_credits', v_refund,
    'available_credits', v_wallet.available_credits,
    'reserved_balance', v_wallet.reserved_credits);
end;
$$;

create or replace function public.release_user_credit_reservation(
  p_user_id uuid,
  p_reservation_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_reservation public.credit_reservations%rowtype;
  v_wallet public.credit_wallets%rowtype;
begin
  if p_user_id is null or p_reservation_id is null then
    raise exception 'Invalid credit release parameters';
  end if;

  select * into v_reservation from public.credit_reservations
   where id = p_reservation_id and user_id = p_user_id for update;
  if not found then raise exception 'Credit reservation not found'; end if;

  if v_reservation.status = 'released' then
    return jsonb_build_object('status', 'already_released');
  end if;
  if v_reservation.status <> 'reserved' then
    raise exception 'Reservation cannot be released from current status';
  end if;

  update public.credit_wallets
    set available_credits = available_credits + v_reservation.reserved_credits,
        reserved_credits = reserved_credits - v_reservation.reserved_credits,
        updated_at = now()
    where user_id = p_user_id
    returning * into v_wallet;

  update public.credit_reservations
    set status = 'released', updated_at = now()
    where id = p_reservation_id returning * into v_reservation;

  insert into public.credit_ledger(user_id, event_type, available_delta,
    reserved_delta, reservation_id, source, operation_code, pricing_version)
  values (p_user_id, 'release', v_reservation.reserved_credits,
    -v_reservation.reserved_credits, p_reservation_id, 'operation',
    v_reservation.operation_code, v_reservation.pricing_version);

  return jsonb_build_object('status', 'released',
    'available_credits', v_wallet.available_credits,
    'reserved_balance', v_wallet.reserved_credits);
end;
$$;

revoke all on function public.grant_user_credits(uuid, bigint, text, text) from public, anon, authenticated;
revoke all on function public.reserve_user_credits(uuid, text, text, integer, bigint) from public, anon, authenticated;
revoke all on function public.settle_user_credit_reservation(uuid, uuid, bigint) from public, anon, authenticated;
revoke all on function public.release_user_credit_reservation(uuid, uuid) from public, anon, authenticated;
grant execute on function public.grant_user_credits(uuid, bigint, text, text) to service_role;
grant execute on function public.reserve_user_credits(uuid, text, text, integer, bigint) to service_role;
grant execute on function public.settle_user_credit_reservation(uuid, uuid, bigint) to service_role;
grant execute on function public.release_user_credit_reservation(uuid, uuid) to service_role;

comment on table public.credit_wallets is 'Server-managed unified PWA Studio credit balances.';
comment on table public.credit_ledger is 'Append-only audit trail for grants, reservations, captures, and releases.';
comment on table public.credit_reservations is 'Idempotent lifecycle records for credit-backed creative operations.';
