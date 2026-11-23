-- PWA Studio: atomic payment order creation and verified-event intake.
-- This layer accepts normalized events only after a provider adapter has
-- verified the raw webhook body and signature. It never grants credits.

create or replace function public.create_payment_order(
  p_user_id uuid,
  p_provider_code text,
  p_merchant_reference text,
  p_idempotency_key uuid,
  p_amount_minor bigint,
  p_currency_code text,
  p_description text,
  p_metadata jsonb default '{}'::jsonb
)
returns table(payment_order_id uuid, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_order public.payment_orders%rowtype;
  v_id uuid;
begin
  if p_user_id is null
     or p_provider_code is null or p_provider_code !~ '^[a-z][a-z0-9_]{1,39}$'
     or p_merchant_reference is null or length(p_merchant_reference) not between 8 and 120
     or p_idempotency_key is null
     or p_amount_minor is null or p_amount_minor <= 0 or p_amount_minor > 1000000000000000
     or p_currency_code is null or p_currency_code !~ '^[A-Z]{3}$'
     or p_description is null or length(p_description) not between 1 and 240
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 4096 then
    raise exception 'invalid payment order parameters' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended(p_user_id::text || ':' || p_idempotency_key::text, 0)
  );

  select * into v_order
    from public.payment_orders
   where user_id = p_user_id and idempotency_key = p_idempotency_key
   for update;

  if found then
    if v_order.provider_code is distinct from p_provider_code
       or v_order.amount_minor is distinct from p_amount_minor
       or v_order.currency_code is distinct from p_currency_code
       or v_order.description is distinct from p_description
       or v_order.metadata is distinct from p_metadata then
      raise exception 'payment idempotency key reused with different order data'
        using errcode = '22023';
    end if;
    return query select v_order.id, true;
    return;
  end if;

  insert into public.payment_orders(
    user_id, provider_code, merchant_reference, idempotency_key,
    amount_minor, currency_code, description, metadata
  ) values (
    p_user_id, p_provider_code, p_merchant_reference, p_idempotency_key,
    p_amount_minor, p_currency_code, p_description, p_metadata
  ) returning id into v_id;

  insert into public.payment_order_events(
    payment_order_id, actor_type, event_type, previous_status,
    new_status, reason_code
  ) values (
    v_id, 'system', 'order.created', null, 'created', 'order_created'
  );

  return query select v_id, false;
end;
$$;

create or replace function public.record_verified_payment_provider_event(
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
    select status into v_new_status from public.payment_orders
     where id = p_payment_order_id;
    return query select v_event.id, true, v_new_status;
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

revoke all on function public.create_payment_order(uuid,text,text,uuid,bigint,text,text,jsonb)
  from public, anon, authenticated;
revoke all on function public.record_verified_payment_provider_event(text,text,uuid,text,text,bigint,text,text)
  from public, anon, authenticated;
grant execute on function public.create_payment_order(uuid,text,text,uuid,bigint,text,text,jsonb)
  to service_role;
grant execute on function public.record_verified_payment_provider_event(text,text,uuid,text,text,bigint,text,text)
  to service_role;

comment on function public.record_verified_payment_provider_event(text,text,uuid,text,text,bigint,text,text) is
  'Service-role only. Call only after a configured provider adapter verifies the raw webhook signature and normalizes its payload. Never grants credits.';
