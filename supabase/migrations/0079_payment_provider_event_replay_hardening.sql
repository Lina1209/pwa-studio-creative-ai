-- Harden idempotent provider-event replay against inconsistent normalized fields.
-- The raw payload digest is necessary but not sufficient: the RPC also receives
-- normalized amount, currency and provider payment id as separate arguments.
-- Re-check those facts against the immutable order on every replay.

create or replace function public.record_verified_payment_provider_event_base(
  p_provider_code text,
  p_provider_event_id text,
  p_payment_order_id uuid,
  p_event_type text,
  p_payload_sha256 text,
  p_amount_minor bigint,
  p_currency_code text,
  p_provider_payment_id text
)
returns table(event_id uuid, replayed boolean, resulting_status text)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_event public.payment_provider_events%rowtype;
  v_order public.payment_orders%rowtype;
  v_event_id uuid;
  v_new_status text;
begin
  if p_provider_code is null or p_provider_code !~ '^[a-z][a-z0-9_]{1,39}$'
     or p_provider_event_id is null or length(p_provider_event_id) not between 1 and 240
     or p_payment_order_id is null
     or p_event_type is null or p_event_type not in (
       'payment.pending', 'payment.succeeded', 'payment.failed', 'payment.cancelled'
     )
     or p_payload_sha256 is null or p_payload_sha256 !~ '^[a-f0-9]{64}$'
     or p_amount_minor is null or p_amount_minor <= 0
     or p_currency_code is null or p_currency_code !~ '^[A-Z]{3}$'
     or p_provider_payment_id is null or length(p_provider_payment_id) not between 1 and 240 then
    raise exception 'invalid normalized payment event' using errcode = '22023';
  end if;

  -- Serialize retries of one provider event before examining its digest.
  perform pg_advisory_xact_lock(
    hashtextextended(p_provider_code || ':' || p_provider_event_id, 0)
  );

  select * into v_event
    from public.payment_provider_events
   where provider_code = p_provider_code
     and provider_event_id = p_provider_event_id;

  if found then
    if v_event.payload_sha256 is distinct from p_payload_sha256
       or v_event.payment_order_id is distinct from p_payment_order_id
       or v_event.event_type is distinct from p_event_type then
      raise exception 'provider event identifier reused with different payload'
        using errcode = '23505';
    end if;

    -- Do not let a matching event digest bypass validation of separately
    -- supplied normalized values. Lock the order to make this check coherent
    -- with any concurrent state transition.
    select * into v_order
      from public.payment_orders
     where id = p_payment_order_id
     for update;

    if not found then
      raise exception 'payment order not found' using errcode = 'P0002';
    end if;
    if v_order.provider_code is distinct from p_provider_code
       or v_order.amount_minor is distinct from p_amount_minor
       or v_order.currency_code is distinct from p_currency_code then
      raise exception 'provider event does not match payment order'
        using errcode = '23514';
    end if;
    if v_order.provider_payment_id is not null
       and v_order.provider_payment_id is distinct from p_provider_payment_id then
      raise exception 'provider payment identifier mismatch'
        using errcode = '23514';
    end if;

    return query select v_event.id, true, v_order.status;
    return;
  end if;

  select * into v_order
    from public.payment_orders
   where id = p_payment_order_id
   for update;

  if not found then
    raise exception 'payment order not found' using errcode = 'P0002';
  end if;
  if v_order.provider_code is distinct from p_provider_code
     or v_order.amount_minor is distinct from p_amount_minor
     or v_order.currency_code is distinct from p_currency_code then
    raise exception 'provider event does not match payment order' using errcode = '23514';
  end if;
  if v_order.provider_payment_id is not null
     and v_order.provider_payment_id is distinct from p_provider_payment_id then
    raise exception 'provider payment identifier mismatch' using errcode = '23514';
  end if;

  insert into public.payment_provider_events(
    provider_code, provider_event_id, payment_order_id, event_type,
    payload_sha256, signature_verified, processing_status, processed_at
  ) values (
    p_provider_code, p_provider_event_id, p_payment_order_id, p_event_type,
    p_payload_sha256, true, 'processed', now()
  ) returning id into v_event_id;

  if p_event_type = 'payment.pending' then
    if v_order.status = 'created' then
      v_new_status := 'pending';
    elsif v_order.status = 'pending' then
      v_new_status := 'pending';
    else
      raise exception 'pending event conflicts with terminal payment order' using errcode = '55000';
    end if;
  elsif p_event_type = 'payment.succeeded' then
    if v_order.status not in ('created', 'pending', 'succeeded') then
      raise exception 'success event conflicts with payment order state' using errcode = '55000';
    end if;
    v_new_status := 'succeeded';
  elsif p_event_type = 'payment.failed' then
    if v_order.status not in ('created', 'pending', 'failed') then
      raise exception 'failure event conflicts with payment order state' using errcode = '55000';
    end if;
    v_new_status := 'failed';
  else
    if v_order.status not in ('created', 'pending', 'cancelled') then
      raise exception 'cancellation event conflicts with payment order state' using errcode = '55000';
    end if;
    v_new_status := 'cancelled';
  end if;

  if v_new_status is distinct from v_order.status then
    update public.payment_orders
       set status = v_new_status,
           provider_payment_id = coalesce(provider_payment_id, p_provider_payment_id),
           paid_at = case when v_new_status = 'succeeded' then now() else paid_at end,
           closed_at = case when v_new_status in ('failed', 'cancelled') then now() else null end
     where id = p_payment_order_id;

    insert into public.payment_order_events(
      payment_order_id, actor_type, event_type, previous_status,
      new_status, reason_code
    ) values (
      p_payment_order_id, 'provider', p_event_type,
      v_order.status, v_new_status,
      replace(p_event_type, '.', '_')
    );
  else
    update public.payment_orders
       set provider_payment_id = coalesce(provider_payment_id, p_provider_payment_id)
     where id = p_payment_order_id;
  end if;

  return query select v_event_id, false, v_new_status;
end;
$$;

comment on function public.record_verified_payment_provider_event_base(text,text,uuid,text,text,bigint,text,text) is
  'Internal service-role base RPC. Revalidates normalized order amount, currency and provider payment id on replay. Call only after provider-specific raw-body signature verification.';