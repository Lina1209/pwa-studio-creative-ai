-- PWA Studio: exactly-once payment fulfillment.
-- Entitlement creation and outbox completion commit or roll back together.
-- No webhook adapter, checkout route, billing activation, or live provider is enabled.

alter table public.user_plan_assignment_events
  add column actor_type text not null default 'user'
    check (actor_type in ('user','admin','provider','system'));
alter table public.user_plan_assignment_events
  alter column actor_user_id drop not null;

create or replace function public.fulfill_payment_order(
  p_fulfillment_id uuid,
  p_lease_token uuid
)
returns table(fulfillment_status text, purchase_type text,
              entitlement_reference text, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_outbox public.payment_fulfillment_outbox%rowtype;
  v_order public.payment_orders%rowtype;
  v_item public.payment_order_purchase_items%rowtype;
  v_existing_lot public.credit_lots%rowtype;
  v_assignment public.user_plan_assignments%rowtype;
  v_start timestamptz;
  v_end timestamptz;
  v_last_end timestamptz;
  v_event_type text;
  v_entitlement_reference text;
begin
  if p_fulfillment_id is null or p_lease_token is null then
    raise exception 'fulfillment id and lease token are required' using errcode = '22023';
  end if;

  select * into v_outbox
    from public.payment_fulfillment_outbox
   where id = p_fulfillment_id
   for update;
  if not found then
    raise exception 'payment fulfillment record not found' using errcode = 'P0002';
  end if;

  if v_outbox.status = 'completed' then
    select * into v_item from public.payment_order_purchase_items
     where payment_order_id = v_outbox.payment_order_id;
    if not found then
      raise exception 'completed fulfillment has no immutable purchase snapshot'
        using errcode = '23514';
    end if;
    if v_item.item_type = 'credit_pack' then
      if not exists (
        select 1 from public.credit_lots
         where user_id = v_item.user_id
           and idempotency_key = 'payment-order:' || v_item.payment_order_id::text
           and source_reference = 'payment-order:' || v_item.payment_order_id::text
           and granted_credits = v_item.credit_quantity
      ) then
        raise exception 'completed credit fulfillment has no matching credit lot'
          using errcode = '23514';
      end if;
    else
      if not exists (
        select 1 from public.user_plan_assignments
         where user_id = v_item.user_id
           and idempotency_key = 'payment-order:' || v_item.payment_order_id::text
           and source_reference = 'payment-order:' || v_item.payment_order_id::text
           and approved_plan_version_id = v_item.approved_plan_version_id
      ) then
        raise exception 'completed subscription fulfillment has no matching assignment'
          using errcode = '23514';
      end if;
    end if;
    return query select 'completed'::text, v_item.item_type,
      'payment-order:' || v_item.payment_order_id::text, true;
    return;
  end if;

  if v_outbox.status <> 'processing'
     or v_outbox.lock_token is distinct from p_lease_token
     or v_outbox.lease_expires_at is null
     or v_outbox.lease_expires_at <= now() then
    return query select 'lease_lost'::text, null::text, null::text, false;
    return;
  end if;

  select * into v_order from public.payment_orders
   where id = v_outbox.payment_order_id
   for update;
  if not found or v_order.status <> 'succeeded'
     or v_order.user_id is distinct from v_outbox.user_id
     or v_order.provider_code is distinct from v_outbox.provider_code
     or v_order.amount_minor is distinct from v_outbox.amount_minor
     or v_order.currency_code is distinct from v_outbox.currency_code then
    raise exception 'settled payment order does not match fulfillment handoff'
      using errcode = '23514';
  end if;

  select * into v_item from public.payment_order_purchase_items
   where payment_order_id = v_order.id
   for update;
  if not found or v_item.user_id is distinct from v_order.user_id
     or v_item.amount_minor is distinct from v_order.amount_minor
     or v_item.currency_code is distinct from v_order.currency_code then
    raise exception 'payment order has no matching approved purchase snapshot'
      using errcode = '23514';
  end if;

  v_entitlement_reference := 'payment-order:' || v_order.id::text;

  if v_item.item_type = 'credit_pack' then
    if v_item.approved_credit_pack_version_id is null
       or v_item.credit_validity_days is null
       or not exists (
         select 1 from public.approved_credit_pack_versions p
          where p.id = v_item.approved_credit_pack_version_id
            and p.sku_code = v_item.sku_code
            and p.sku_version = v_item.sku_version
            and p.credits = v_item.credit_quantity
            and p.price_minor = v_item.amount_minor
            and p.currency = v_item.currency_code
            and p.credit_validity_days = v_item.credit_validity_days
       ) then
      raise exception 'credit pack purchase snapshot no longer matches approved catalog'
        using errcode = '23514';
    end if;

    perform public.grant_user_credit_lot(
      v_item.user_id,
      v_item.credit_quantity,
      'purchased',
      v_entitlement_reference,
      v_entitlement_reference,
      now() + make_interval(days => v_item.credit_validity_days),
      jsonb_build_object(
        'source', 'verified_payment',
        'payment_order_id', v_order.id,
        'approved_credit_pack_version_id', v_item.approved_credit_pack_version_id,
        'sku_code', v_item.sku_code,
        'sku_version', v_item.sku_version,
        'amount_minor', v_item.amount_minor,
        'currency_code', v_item.currency_code
      )
    );
  elsif v_item.item_type = 'subscription' then
    if v_item.approved_plan_version_id is null
       or v_item.plan_period_days is null
       or not exists (
         select 1 from public.approved_plan_versions p
          where p.id = v_item.approved_plan_version_id
            and p.plan_code = v_item.sku_code
            and p.plan_version = v_item.sku_version
            and p.credits_per_period = v_item.credit_quantity
            and p.period_days = v_item.plan_period_days
            and p.price_minor = v_item.amount_minor
            and p.currency = v_item.currency_code
       ) then
      raise exception 'subscription purchase snapshot no longer matches approved plan'
        using errcode = '23514';
    end if;

    -- Stack a paid period after any currently active or already scheduled period.
    select max(a.ends_at) into v_last_end
      from public.user_plan_assignments a
      join lateral (
        select e.event_type
          from public.user_plan_assignment_events e
         where e.assignment_id = a.id
         order by e.occurred_at desc, e.id desc
         limit 1
      ) latest_event on latest_event.event_type in ('activated','scheduled')
     where a.user_id = v_item.user_id
       and a.ends_at > now();

    v_start := greatest(now(), coalesce(v_last_end, now()));
    v_end := v_start + make_interval(days => v_item.plan_period_days);
    v_event_type := case when v_start > now() then 'scheduled' else 'activated' end;

    insert into public.user_plan_assignments(
      user_id, approved_plan_version_id, assignment_source,
      source_reference, idempotency_key, status, starts_at, ends_at,
      created_by, metadata
    ) values (
      v_item.user_id, v_item.approved_plan_version_id, 'verified_payment',
      v_entitlement_reference, v_entitlement_reference, 'pending',
      v_start, v_end, v_item.user_id,
      jsonb_build_object(
        'created_by_actor_type', 'system',
        'payment_order_id', v_order.id,
        'amount_minor', v_item.amount_minor,
        'currency_code', v_item.currency_code,
        'sku_code', v_item.sku_code,
        'sku_version', v_item.sku_version
      )
    )
    on conflict (user_id, idempotency_key) do nothing
    returning * into v_assignment;

    if v_assignment.id is null then
      select * into v_assignment from public.user_plan_assignments
       where user_id = v_item.user_id and idempotency_key = v_entitlement_reference
       for update;
      if not found
         or v_assignment.approved_plan_version_id is distinct from v_item.approved_plan_version_id
         or v_assignment.source_reference is distinct from v_entitlement_reference
         or v_assignment.ends_at <= v_assignment.starts_at then
        raise exception 'subscription assignment idempotency conflict'
          using errcode = '23514';
      end if;
      v_event_type := case when v_assignment.starts_at > now()
        then 'scheduled' else 'activated' end;
    end if;

    insert into public.user_plan_assignment_events(
      assignment_id, user_id, event_type, actor_user_id, actor_type,
      event_key, reason, metadata
    ) values (
      v_assignment.id, v_item.user_id, 'created', null, 'system',
      'payment-created:' || v_order.id::text,
      'Created from verified settled payment order',
      jsonb_build_object('payment_order_id', v_order.id)
    ) on conflict (assignment_id, event_key) do nothing;

    insert into public.user_plan_assignment_events(
      assignment_id, user_id, event_type, actor_user_id, actor_type,
      event_key, reason, metadata
    ) values (
      v_assignment.id, v_item.user_id, v_event_type, null, 'system',
      'payment-' || v_event_type || ':' || v_order.id::text,
      case when v_event_type = 'activated'
        then 'Activated from verified settled payment order'
        else 'Scheduled after the existing paid plan period' end,
      jsonb_build_object('payment_order_id', v_order.id)
    ) on conflict (assignment_id, event_key) do nothing;
  else
    raise exception 'unsupported payment purchase type' using errcode = '23514';
  end if;

  -- The entitlement and this fenced completion update share this transaction.
  -- If any step fails, neither the entitlement nor completed state is committed.
  update public.payment_fulfillment_outbox
     set status = 'completed',
         locked_at = null,
         lock_token = null,
         lease_expires_at = null,
         completed_at = now(),
         last_error_code = null
   where id = v_outbox.id
     and status = 'processing'
     and lock_token = p_lease_token
     and lease_expires_at > now();

  if not found then
    raise exception 'fulfillment lease expired before atomic completion'
      using errcode = '40001';
  end if;

  return query select 'completed'::text, v_item.item_type,
    v_entitlement_reference, false;
end;
$$;

-- A worker may no longer mark a payment completed without creating its entitlement.
revoke all on function public.complete_payment_fulfillment(uuid,uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.fulfill_payment_order(uuid,uuid)
  from public, anon, authenticated;
grant execute on function public.fulfill_payment_order(uuid,uuid)
  to service_role;

comment on function public.fulfill_payment_order(uuid,uuid) is
  'Service-role only. Validates the live worker lease, settled order and immutable approved purchase snapshot; creates exactly one credit lot or plan assignment and completes the outbox in the same transaction.';
