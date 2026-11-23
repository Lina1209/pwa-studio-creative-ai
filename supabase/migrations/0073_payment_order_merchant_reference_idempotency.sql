-- PWA Studio: reject merchant-reference changes on payment-order replay.
-- Existing orders are immutable; a reused idempotency key must match every
-- identity and pricing field, including the provider-facing merchant reference.
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
       or v_order.merchant_reference is distinct from p_merchant_reference
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


comment on function public.create_payment_order(uuid,text,text,uuid,bigint,text,text,jsonb) is
  'Creates an immutable payment order; replay requires an exact match of provider, merchant reference, amount, currency, description and metadata. Does not grant credits.';
