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
\i supabase/migrations/0070_payment_order_merchant_reference_idempotency.sql

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
end;
$payment_success_event_idempotency_test$;
