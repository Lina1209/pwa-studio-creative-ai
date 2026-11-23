-- End-to-end payment entitlement integration tests.
-- Run after generation_jobs_migration_test.sql and payment_order_migration_test.sql.

\set ON_ERROR_STOP on
\ir ../migrations/0078_atomic_payment_fulfillment.sql
\ir ../migrations/0100_finance_integrity_payments_subscriptions_quotas.sql

insert into auth.users(id)
values
  ('33333333-3333-4333-8333-333333333333'),
  ('88888888-8888-4888-8888-888888888888')
on conflict (id) do nothing;

insert into public.approved_credit_pack_versions(
  id, sku_code, sku_version, display_name, credits, price_minor,
  currency, credit_validity_days, approved_by, approval_reason
) values (
  '44444444-4444-4444-8444-444444444444',
  'mini_topup', 1, 'Mini Top-up', 850, 99000,
  'KZT', 365, '11111111-1111-4111-8111-111111111111',
  'Approved test credit pack version'
);

insert into public.plan_catalog_drafts(
  id, plan_code, plan_version, display_name, billing_period, period_days,
  credits_per_period, price_minor, currency, limits_json, features_json, created_by
) values (
  '55555555-5555-4555-8555-555555555555',
  'payment_test_plan', 1, 'Payment Test Plan', 'month', 30,
  1300, 149000, 'KZT', '{}'::jsonb, '["image","video"]'::jsonb,
  '11111111-1111-4111-8111-111111111111'
);

insert into public.approved_plan_versions(
  id, source_draft_id, plan_code, plan_version, display_name,
  billing_period, period_days, credits_per_period, price_minor, currency,
  limits_json, features_json, approved_by, approval_reason
) values (
  '66666666-6666-4666-8666-666666666666',
  '55555555-5555-4555-8555-555555555555',
  'payment_test_plan', 1, 'Payment Test Plan', 'month', 30,
  1300, 149000, 'KZT', '{}'::jsonb, '["image","video"]'::jsonb,
  '11111111-1111-4111-8111-111111111111',
  'Approved test plan version for payment fulfillment'
);

do $payment_credit_pack_exactly_once$
declare
  v_order record;
  v_event record;
  v_claim record;
  v_result record;
  v_replay record;
  v_lots bigint;
  v_grants bigint;
  v_balance bigint;
  v_status text;
begin
  select * into v_order from public.create_credit_pack_payment_order(
    '88888888-8888-4888-8888-888888888888',
    'examplepay',
    'purchase-credit-pack-001',
    'aaaaaaaa-1111-4111-8111-111111111111',
    '44444444-4444-4444-8444-444444444444',
    '{"source":"integration_test"}'::jsonb
  );

  select * into v_event from public.record_verified_payment_provider_event(
    'examplepay', 'purchase-credit-pack-event-001',
    v_order.payment_order_id, 'payment.succeeded', repeat('c',64),
    99000, 'KZT', 'purchase-credit-pack-provider-payment-001'
  );
  if v_event.resulting_status <> 'succeeded' or v_event.replayed then
    raise exception 'Credit pack payment did not settle as expected';
  end if;

  select * into v_claim from public.claim_payment_fulfillment(120,1);
  if v_claim.payment_order_id <> v_order.payment_order_id
     or v_claim.lease_token is null then
    raise exception 'Credit pack fulfillment was not claimed';
  end if;

  select * into v_result from public.fulfill_payment_order(
    v_claim.fulfillment_id, v_claim.lease_token
  );
  if v_result.fulfillment_status <> 'completed'
     or v_result.purchase_type <> 'credit_pack'
     or v_result.replayed then
    raise exception 'Credit pack entitlement was not fulfilled exactly once';
  end if;

  select * into v_replay from public.fulfill_payment_order(
    v_claim.fulfillment_id, v_claim.lease_token
  );
  if v_replay.fulfillment_status <> 'completed' or not v_replay.replayed then
    raise exception 'Completed credit fulfillment replay was not idempotent';
  end if;

  select count(*) into v_lots from public.credit_lots
   where user_id = '88888888-8888-4888-8888-888888888888'
     and idempotency_key = 'payment-order:' || v_order.payment_order_id::text;
  select count(*) into v_grants from public.credit_ledger
   where user_id = '88888888-8888-4888-8888-888888888888'
     and operation_key = 'grant:payment-order:' || v_order.payment_order_id::text;
  select available_credits into v_balance from public.credit_wallets
   where user_id = '88888888-8888-4888-8888-888888888888';
  select status into v_status from public.payment_fulfillment_outbox
   where id = v_claim.fulfillment_id;

  if v_lots <> 1 or v_grants <> 1 or v_balance <> 850 or v_status <> 'completed' then
    raise exception 'Credit grant, wallet projection or outbox completion was duplicated or inconsistent';
  end if;
end;
$payment_credit_pack_exactly_once$;

do $payment_subscription_exactly_once$
declare
  v_order record;
  v_event record;
  v_claim record;
  v_result record;
  v_replay record;
  v_assignment_id uuid;
  v_assignment_count bigint;
  v_created_events bigint;
  v_activated_events bigint;
  v_latest_event text;
begin
  select * into v_order from public.create_subscription_payment_order(
    '33333333-3333-4333-8333-333333333333',
    'examplepay',
    'purchase-subscription-001',
    'bbbbbbbb-1111-4111-8111-111111111111',
    '66666666-6666-4666-8666-666666666666',
    '{}'::jsonb
  );

  select * into v_event from public.record_verified_payment_provider_event(
    'examplepay', 'purchase-subscription-event-001',
    v_order.payment_order_id, 'payment.succeeded', repeat('d',64),
    149000, 'KZT', 'purchase-subscription-provider-payment-001'
  );
  if v_event.resulting_status <> 'succeeded' then
    raise exception 'Subscription payment did not settle';
  end if;

  select * into v_claim from public.claim_payment_fulfillment(120,1);
  if v_claim.payment_order_id <> v_order.payment_order_id then
    raise exception 'Subscription fulfillment was not claimed';
  end if;

  select * into v_result from public.fulfill_payment_order(
    v_claim.fulfillment_id, v_claim.lease_token
  );
  if v_result.fulfillment_status <> 'completed'
     or v_result.purchase_type <> 'subscription'
     or v_result.replayed then
    raise exception 'Subscription assignment was not created atomically';
  end if;

  select * into v_replay from public.fulfill_payment_order(
    v_claim.fulfillment_id, v_claim.lease_token
  );
  if not v_replay.replayed then
    raise exception 'Completed subscription fulfillment replay was not idempotent';
  end if;

  select id into v_assignment_id from public.user_plan_assignments
   where user_id = '33333333-3333-4333-8333-333333333333'
     and idempotency_key = 'payment-order:' || v_order.payment_order_id::text;
  select count(*) into v_assignment_count from public.user_plan_assignments
   where user_id = '33333333-3333-4333-8333-333333333333'
     and idempotency_key = 'payment-order:' || v_order.payment_order_id::text;
  select count(*) into v_created_events from public.user_plan_assignment_events
   where assignment_id = v_assignment_id and event_type = 'created'
     and actor_type = 'system' and actor_user_id is null;
  select count(*) into v_activated_events from public.user_plan_assignment_events
   where assignment_id = v_assignment_id and event_type = 'activated'
     and actor_type = 'system' and actor_user_id is null;
  select event_type into v_latest_event from public.user_plan_assignment_events
   where assignment_id = v_assignment_id
   order by occurred_at desc, id desc limit 1;

  if v_assignment_count <> 1 or v_created_events <> 1
     or v_activated_events <> 1 or v_latest_event <> 'activated' then
    raise exception 'Subscription assignment or lifecycle event was duplicated or not activated';
  end if;
end;
$payment_subscription_exactly_once$;

do $payment_scheduled_plan_activation_worker$
declare
  v_activated integer;
  v_assignment_id uuid := '77777777-7777-4777-8777-777777777777';
  v_latest_event text;
begin
  insert into public.user_plan_assignments(
    id, user_id, approved_plan_version_id, assignment_source,
    source_reference, idempotency_key, status, starts_at, ends_at, created_by
  ) values (
    v_assignment_id,
    '33333333-3333-4333-8333-333333333333',
    '66666666-6666-4666-8666-666666666666',
    'verified_payment',
    'payment-order:scheduled-fixture',
    'payment-order:scheduled-fixture',
    'pending',
    now() - interval '1 minute',
    now() + interval '30 days',
    '33333333-3333-4333-8333-333333333333'
  );

  insert into public.user_plan_assignment_events(
    assignment_id, user_id, event_type, actor_user_id, actor_type, event_key, reason
  ) values
  (
    v_assignment_id, '33333333-3333-4333-8333-333333333333',
    'created', null, 'system', 'scheduled-fixture-created',
    'Created scheduled payment test assignment'
  ),
  (
    v_assignment_id, '33333333-3333-4333-8333-333333333333',
    'scheduled', null, 'system', 'scheduled-fixture-scheduled',
    'Scheduled payment test assignment'
  );

  select public.activate_due_payment_plan_assignments(10) into v_activated;
  if v_activated <> 1 then
    raise exception 'Due payment-backed plan assignment was not activated';
  end if;

  select event_type into v_latest_event
    from public.user_plan_assignment_events
   where assignment_id = v_assignment_id
   order by occurred_at desc, id desc limit 1;
  if v_latest_event <> 'activated' then
    raise exception 'Activation worker did not append the activated lifecycle event';
  end if;

  select public.activate_due_payment_plan_assignments(10) into v_activated;
  if v_activated <> 0 then
    raise exception 'Activation worker duplicated an already-appended activation event';
  end if;
end;
$payment_scheduled_plan_activation_worker$;

do $payment_subscription_period_stacking$
declare
  v_order record;
  v_event record;
  v_claim record;
  v_result record;
  v_assignment public.user_plan_assignments%rowtype;
  v_prior_end timestamptz;
  v_latest_event text;
begin
  select max(a.ends_at) into v_prior_end
    from public.user_plan_assignments a
    join lateral (
      select e.event_type
        from public.user_plan_assignment_events e
       where e.assignment_id = a.id
       order by e.occurred_at desc, e.id desc
       limit 1
    ) latest_event on latest_event.event_type in ('activated','scheduled')
   where a.user_id = '33333333-3333-4333-8333-333333333333'
     and a.ends_at > now();

  select * into v_order from public.create_subscription_payment_order(
    '33333333-3333-4333-8333-333333333333',
    'examplepay',
    'purchase-subscription-002',
    'cccccccc-1111-4111-8111-111111111111',
    '66666666-6666-4666-8666-666666666666',
    '{}'::jsonb
  );

  select * into v_event from public.record_verified_payment_provider_event(
    'examplepay', 'purchase-subscription-event-002',
    v_order.payment_order_id, 'payment.succeeded', repeat('e',64),
    149000, 'KZT', 'purchase-subscription-provider-payment-002'
  );
  if v_event.resulting_status <> 'succeeded' then
    raise exception 'Second subscription payment did not settle';
  end if;

  select * into v_claim from public.claim_payment_fulfillment(120,1);
  if v_claim.payment_order_id <> v_order.payment_order_id then
    raise exception 'Second subscription fulfillment was not claimed';
  end if;

  select * into v_result from public.fulfill_payment_order(
    v_claim.fulfillment_id, v_claim.lease_token
  );
  if v_result.fulfillment_status <> 'completed' then
    raise exception 'Second subscription fulfillment did not complete';
  end if;

  select * into v_assignment from public.user_plan_assignments
   where user_id = '33333333-3333-4333-8333-333333333333'
     and idempotency_key = 'payment-order:' || v_order.payment_order_id::text;
  select event_type into v_latest_event
    from public.user_plan_assignment_events
   where assignment_id = v_assignment.id
   order by occurred_at desc, id desc limit 1;

  if v_prior_end is null or v_assignment.starts_at < v_prior_end
     or v_latest_event <> 'scheduled' then
    raise exception 'Second paid subscription overlaps an existing paid period';
  end if;
end;
$payment_subscription_period_stacking$;

do $payment_fulfillment_privilege_boundary$
begin
  if has_function_privilege(
    'service_role',
    'public.complete_payment_fulfillment(uuid,uuid)',
    'EXECUTE'
  ) then
    raise exception 'Workers can still complete a payment without entitlement fulfillment';
  end if;
  if not has_function_privilege(
    'service_role',
    'public.fulfill_payment_order(uuid,uuid)',
    'EXECUTE'
  ) then
    raise exception 'Service role cannot call the atomic payment fulfillment RPC';
  end if;
end;
$payment_fulfillment_privilege_boundary$;


-- The expanded finance snapshot sees successful credit-pack and subscription
-- purchases, their immutable purchase snapshots, fulfillment records and
-- entitlements from one statement snapshot. It remains service-role-only.
do $finance_commerce_snapshot_test$
declare
  v_credit jsonb;
  v_subscription jsonb;
begin
  if not has_function_privilege(
       'service_role',
       'public.get_finance_integrity_audit_snapshot(uuid)',
       'EXECUTE'
     )
     or has_function_privilege(
       'authenticated',
       'public.get_finance_integrity_audit_snapshot(uuid)',
       'EXECUTE'
     )
     or has_function_privilege(
       'anon',
       'public.get_finance_integrity_audit_snapshot(uuid)',
       'EXECUTE'
     ) then
    raise exception 'Expanded finance snapshot RPC privileges are not service-role-only';
  end if;

  v_credit := public.get_finance_integrity_audit_snapshot(
    '88888888-8888-4888-8888-888888888888'
  );
  if v_credit ->> 'complete' <> 'true'
     or (v_credit -> 'counts' ->> 'payment_orders')::integer <> 1
     or (v_credit -> 'counts' ->> 'payment_provider_events')::integer <> 1
     or (v_credit -> 'counts' ->> 'purchase_items')::integer <> 1
     or (v_credit -> 'counts' ->> 'fulfillment_outbox')::integer <> 1
     or (v_credit -> 'counts' ->> 'lots')::integer <> 1 then
    raise exception 'Credit-pack finance snapshot is incomplete or missing settlement/fulfillment evidence: %', v_credit;
  end if;

  v_subscription := public.get_finance_integrity_audit_snapshot(
    '33333333-3333-4333-8333-333333333333'
  );
  if v_subscription ->> 'complete' <> 'true'
     or (v_subscription -> 'counts' ->> 'payment_orders')::integer <> 2
     or (v_subscription -> 'counts' ->> 'plan_assignments')::integer < 2
     or (v_subscription -> 'counts' ->> 'plan_assignment_events')::integer < 4
     or (v_subscription -> 'counts' ->> 'approved_plans')::integer <> 1 then
    raise exception 'Subscription finance snapshot is incomplete or missing plan entitlement evidence: %', v_subscription;
  end if;
end;
$finance_commerce_snapshot_test$;

select 'expanded finance commerce snapshot checks passed' as result;
