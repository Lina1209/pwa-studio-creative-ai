\set ON_ERROR_STOP on
create extension if not exists pgcrypto;
create schema if not exists auth;
do $roles$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end;
$roles$;
create table if not exists auth.users (id uuid primary key);
insert into auth.users(id) values ('11111111-1111-4111-8111-111111111111') on conflict (id) do nothing;
\i supabase/migrations/0052_payment_order_foundation.sql
\i supabase/migrations/0053_payment_order_rpcs.sql
\i supabase/migrations/0073_payment_order_merchant_reference_idempotency.sql
\i supabase/migrations/0072_payment_fulfillment_outbox.sql
\i supabase/migrations/0074_payment_fulfillment_execution_state.sql
\i supabase/migrations/0075_payment_fulfillment_worker_leases.sql
\i supabase/migrations/0076_payment_fulfillment_lease_hardening.sql
\i supabase/migrations/0077_payment_purchase_snapshots.sql

do $payment_order_merchant_reference_idempotency_test$
declare
  v_first record;
  v_replay record;
  v_rejected boolean := false;
begin
  select * into v_first from public.create_payment_order(
    '11111111-1111-4111-8111-111111111111',
    'examplepay',
    'test-merchant-ref-001',
    'aaaaaaaa-0000-4000-8000-000000000001',
    1250,
    'KZT',
    'Test plan purchase',
    '{"plan_code":"starter"}'::jsonb
  );
  select * into v_replay from public.create_payment_order(
    '11111111-1111-4111-8111-111111111111',
    'examplepay',
    'test-merchant-ref-001',
    'aaaaaaaa-0000-4000-8000-000000000001',
    1250,
    'KZT',
    'Test plan purchase',
    '{"plan_code":"starter"}'::jsonb
  );
  if v_replay.payment_order_id <> v_first.payment_order_id or not v_replay.replayed then
    raise exception 'Exact payment order replay did not return the original order';
  end if;
  begin
    perform * from public.create_payment_order(
      '11111111-1111-4111-8111-111111111111',
      'examplepay',
      'different-merchant-ref-001',
      'aaaaaaaa-0000-4000-8000-000000000001',
      1250,
      'KZT',
      'Test plan purchase',
      '{"plan_code":"starter"}'::jsonb
    );
  exception when invalid_parameter_value then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Payment order replay accepted a different merchant reference';
  end if;
end;
$payment_order_merchant_reference_idempotency_test$;

-- Verified success events are idempotent and only settle the order.
do $payment_success_event_idempotency_test$
declare
  v_order_id uuid;
  v_first record;
  v_replay record;
  v_event_count bigint;
  v_fulfillment_count bigint;
  v_status text;
begin
  select id into v_order_id
    from public.payment_orders
   where merchant_reference = 'test-merchant-ref-001';

  select * into v_first from public.record_verified_payment_provider_event(
    'examplepay',
    'provider-event-success-001',
    v_order_id,
    'payment.succeeded',
    repeat('a', 64),
    1250,
    'KZT',
    'provider-payment-001'
  );
  if v_first.replayed or v_first.resulting_status <> 'succeeded' then
    raise exception 'First verified success event did not settle the order exactly once';
  end if;

  select * into v_replay from public.record_verified_payment_provider_event(
    'examplepay',
    'provider-event-success-001',
    v_order_id,
    'payment.succeeded',
    repeat('a', 64),
    1250,
    'KZT',
    'provider-payment-001'
  );
  if not v_replay.replayed or v_replay.resulting_status <> 'succeeded' then
    raise exception 'Duplicate verified success event was not an idempotent replay';
  end if;

  select count(*) into v_event_count
    from public.payment_provider_events
   where provider_code = 'examplepay'
     and provider_event_id = 'provider-event-success-001';
  select status into v_status from public.payment_orders where id = v_order_id;
  if v_event_count <> 1 or v_status <> 'succeeded' then
    raise exception 'Duplicate success event changed payment state or duplicated the inbox row';
  end if;

  select count(*) into v_fulfillment_count
    from public.payment_fulfillment_outbox
   where payment_order_id = v_order_id
     and user_id = '11111111-1111-4111-8111-111111111111'
     and provider_code = 'examplepay'
     and amount_minor = 1250
     and currency_code = 'KZT'
     and status = 'queued';
  if v_fulfillment_count <> 1 then
    raise exception 'Verified successful payment did not create exactly one matching fulfillment handoff';
  end if;
end;
$payment_success_event_idempotency_test$;


-- Mutable execution state cannot alter immutable purchase facts or skip transitions.
do $payment_fulfillment_execution_state_test$
declare
  v_order_id uuid;
  v_rejected boolean := false;
  v_status text;
begin
  select id into v_order_id from public.payment_orders
   where merchant_reference = 'test-merchant-ref-001';

  begin
    update public.payment_fulfillment_outbox
       set status = 'completed', completed_at = now()
     where payment_order_id = v_order_id;
  exception when check_violation then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Fulfillment skipped directly from queued to completed';
  end if;

  v_rejected := false;
  begin
    update public.payment_fulfillment_outbox
       set amount_minor = 1
     where payment_order_id = v_order_id;
  exception when sqlstate '55000' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Immutable payment amount was changed in fulfillment handoff';
  end if;

  update public.payment_fulfillment_outbox
     set status = 'processing',
         attempt_count = 1,
         locked_at = now(),
         lease_expires_at = now() + interval '15 seconds',
         lock_token = 'bbbbbbbb-0000-4000-8000-000000000001'
   where payment_order_id = v_order_id;

  update public.payment_fulfillment_outbox
     set status = 'completed',
         locked_at = null,
         lock_token = null,
         lease_expires_at = null,
         completed_at = now()
   where payment_order_id = v_order_id;

  select status into v_status from public.payment_fulfillment_outbox
   where payment_order_id = v_order_id;
  if v_status <> 'completed' then
    raise exception 'Valid processing-to-completed transition failed';
  end if;
end;
$payment_fulfillment_execution_state_test$;


-- Atomic claim, expired-lease recovery, and stale-worker fencing.
do $payment_fulfillment_worker_lease_test$
declare
  v_order_id uuid;
  v_claim1 record;
  v_claim2 record;
  v_claim3 record;
  v_complete boolean;
  v_status text;
  v_new_order record;
begin
  select * into v_new_order from public.create_payment_order(
    '11111111-1111-4111-8111-111111111111',
    'examplepay',
    'test-merchant-ref-lease-002',
    'aaaaaaaa-0000-4000-8000-000000000002',
    2500,
    'KZT',
    'Lease recovery test purchase',
    '{"plan_code":"starter"}'::jsonb
  );
  perform * from public.record_verified_payment_provider_event(
    'examplepay',
    'provider-event-lease-success-002',
    v_new_order.payment_order_id,
    'payment.succeeded',
    repeat('b', 64),
    2500,
    'KZT',
    'provider-payment-lease-002'
  );

  select * into v_claim1 from public.claim_payment_fulfillment(15, 1);
  if v_claim1.fulfillment_id is null or v_claim1.attempt_count <> 1 then
    raise exception 'Expected the queued fulfillment to be atomically claimed';
  end if;

  select * into v_claim2 from public.claim_payment_fulfillment(15);
  if v_claim2.fulfillment_id is not null then
    raise exception 'A live lease was claimed by a second worker';
  end if;

  -- Simulate a crashed worker by expiring the lease in the isolated test database.
  update public.payment_fulfillment_outbox
     set locked_at = now() - interval '16 seconds',
         lease_expires_at = now() - interval '1 second'
   where id = v_claim1.fulfillment_id;

  select * into v_claim3 from public.claim_payment_fulfillment(15);
  if v_claim3.fulfillment_id <> v_claim1.fulfillment_id
     or v_claim3.lease_token = v_claim1.lease_token
     or v_claim3.attempt_count <> v_claim1.attempt_count + 1 then
    raise exception 'Expired lease was not recovered with a fresh fencing token';
  end if;

  select public.complete_payment_fulfillment(v_claim1.fulfillment_id, v_claim1.lease_token)
    into v_complete;
  if v_complete then
    raise exception 'Stale worker was allowed to complete a reclaimed task';
  end if;

  select public.complete_payment_fulfillment(v_claim3.fulfillment_id, v_claim3.lease_token)
    into v_complete;
  if not v_complete then
    raise exception 'Current lease holder could not complete the task';
  end if;

  select status into v_status from public.payment_fulfillment_outbox
   where id = v_claim3.fulfillment_id;
  if v_status <> 'completed' then
    raise exception 'Fulfillment did not reach completed after valid lease completion';
  end if;
end;
$payment_fulfillment_worker_lease_test$;
