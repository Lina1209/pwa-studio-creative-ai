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
create table auth.users (id uuid primary key);
insert into auth.users(id) values ('11111111-1111-4111-8111-111111111111');
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
