-- Forward-only hardening for ambiguous credit-provider outcomes.
-- Apply only after migration-ledger reconciliation; never rewrite 0013.

alter table public.credit_reservations
  add column if not exists provider_outcome text
    check (provider_outcome is null or provider_outcome in ('succeeded', 'failed')),
  add column if not exists provider_resolution_reference text;

-- A reservation in reconciliation_required cannot be settled or released by
-- the ordinary lifecycle RPCs. Only the explicit resolution RPC below may
-- move it back to reserved after a confirmed provider outcome is supplied.
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
  if p_user_id is null or p_reservation_id is null
     or p_capture_amount is null or p_capture_amount < 0 then
    raise exception 'Invalid credit settlement parameters';
  end if;
  select * into v_wallet from public.credit_wallets where user_id = p_user_id for update;
  if not found then raise exception 'Credit wallet not found'; end if;
  select * into v_reservation from public.credit_reservations
   where id = p_reservation_id and user_id = p_user_id for update;
  if not found then raise exception 'Credit reservation not found'; end if;
  if v_reservation.status = 'settled' then
    if v_reservation.captured_credits <> p_capture_amount then
      raise exception 'Settled reservation replay used a different capture amount';
    end if;
    return jsonb_build_object('status', 'already_settled',
      'captured_credits', v_reservation.captured_credits);
  end if;
  if v_reservation.status <> 'reserved'
     or p_capture_amount > v_reservation.reserved_credits then
    raise exception 'Reservation requires explicit provider resolution or cannot be settled';
  end if;
  v_refund := v_reservation.reserved_credits - p_capture_amount;
  update public.credit_wallets
    set available_credits = available_credits + v_refund,
        reserved_credits = reserved_credits - v_reservation.reserved_credits,
        updated_at = now()
    where user_id = p_user_id returning * into v_wallet;
  update public.credit_reservations
    set status = 'settled', captured_credits = p_capture_amount, updated_at = now()
    where id = p_reservation_id returning * into v_reservation;
  insert into public.credit_ledger(user_id, event_type, available_delta,
    reserved_delta, reservation_id, source, operation_code, pricing_version)
  values (p_user_id, 'capture', v_refund, -v_reservation.reserved_credits,
    p_reservation_id, 'operation', v_reservation.operation_code, v_reservation.pricing_version);
  return jsonb_build_object('status', 'settled',
    'captured_credits', p_capture_amount, 'refunded_credits', v_refund,
    'available_credits', v_wallet.available_credits, 'reserved_balance', v_wallet.reserved_credits);
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
  select * into v_wallet from public.credit_wallets where user_id = p_user_id for update;
  if not found then raise exception 'Credit wallet not found'; end if;
  select * into v_reservation from public.credit_reservations
   where id = p_reservation_id and user_id = p_user_id for update;
  if not found then raise exception 'Credit reservation not found'; end if;
  if v_reservation.status = 'released' then
    return jsonb_build_object('status', 'already_released');
  end if;
  if v_reservation.status <> 'reserved' then
    raise exception 'Reservation requires explicit provider resolution or cannot be released';
  end if;
  update public.credit_wallets
    set available_credits = available_credits + v_reservation.reserved_credits,
        reserved_credits = reserved_credits - v_reservation.reserved_credits,
        updated_at = now()
    where user_id = p_user_id returning * into v_wallet;
  update public.credit_reservations
    set status = 'released', updated_at = now()
    where id = p_reservation_id returning * into v_reservation;
  insert into public.credit_ledger(user_id, event_type, available_delta,
    reserved_delta, reservation_id, source, operation_code, pricing_version)
  values (p_user_id, 'release', v_reservation.reserved_credits,
    -v_reservation.reserved_credits, p_reservation_id, 'operation',
    v_reservation.operation_code, v_reservation.pricing_version);
  return jsonb_build_object('status', 'released',
    'available_credits', v_wallet.available_credits, 'reserved_balance', v_wallet.reserved_credits);
end;
$$;

create or replace function public.resolve_credit_reservation_provider_outcome(
  p_user_id uuid,
  p_reservation_id uuid,
  p_provider_outcome text,
  p_provider_resolution_reference text,
  p_capture_amount bigint default null
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_reservation public.credit_reservations%rowtype;
  v_result jsonb;
begin
  if p_user_id is null or p_reservation_id is null
     or p_provider_outcome is null
     or p_provider_outcome not in ('succeeded', 'failed')
     or p_provider_resolution_reference is null
     or length(p_provider_resolution_reference) not between 1 and 200
     or (p_provider_outcome = 'succeeded' and (p_capture_amount is null or p_capture_amount < 0))
     or (p_provider_outcome = 'failed' and p_capture_amount is not null) then
    raise exception 'Invalid provider resolution parameters';
  end if;

  select * into v_wallet from public.credit_wallets where user_id = p_user_id for update;
  if not found then raise exception 'Credit wallet not found'; end if;
  select * into v_reservation from public.credit_reservations
   where id = p_reservation_id and user_id = p_user_id for update;
  if not found then raise exception 'Credit reservation not found'; end if;

  if v_reservation.status in ('settled', 'released') then
    if v_reservation.provider_outcome = p_provider_outcome
       and v_reservation.provider_resolution_reference = p_provider_resolution_reference then
      return jsonb_build_object('status', 'already_resolved', 'reservation_status', v_reservation.status);
    end if;
    raise exception 'Finalized reservation cannot be resolved again';
  end if;
  if v_reservation.status <> 'reconciliation_required' then
    raise exception 'Only ambiguous reservations can use provider resolution';
  end if;
  if p_provider_outcome = 'succeeded' and p_capture_amount > v_reservation.reserved_credits then
    raise exception 'Capture amount exceeds reserved credits';
  end if;

  update public.credit_reservations
    set provider_outcome = p_provider_outcome,
        provider_resolution_reference = p_provider_resolution_reference,
        status = 'reserved',
        updated_at = now()
    where id = p_reservation_id;

  if p_provider_outcome = 'succeeded' then
    v_result := public.settle_user_credit_reservation(p_user_id, p_reservation_id, p_capture_amount);
  else
    v_result := public.release_user_credit_reservation(p_user_id, p_reservation_id);
  end if;

  return jsonb_build_object(
    'status', 'resolved',
    'provider_outcome', p_provider_outcome,
    'provider_resolution_reference', p_provider_resolution_reference,
    'reservation_result', v_result
  );
end;
$$;

revoke all on function public.resolve_credit_reservation_provider_outcome(uuid, uuid, text, text, bigint)
  from public, anon, authenticated;
grant execute on function public.resolve_credit_reservation_provider_outcome(uuid, uuid, text, text, bigint)
  to service_role;
