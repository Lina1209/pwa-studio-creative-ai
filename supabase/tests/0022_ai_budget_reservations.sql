-- Disposable PostgreSQL contract tests for migration 0022 only.
-- Run after 0019_disposable_supabase_bootstrap.sql and with PWA_TEST_OWNER_ID set.
\set ON_ERROR_STOP on

begin;
select set_config('pwa.test_owner_id', :'PWA_TEST_OWNER_ID', true);

insert into public.ai_budget_policies(
  scope_type,scope_key,period_start,period_end,limit_usd,enabled
) values (
  'platform','platform',date_trunc('month',now()),date_trunc('month',now()) + interval '1 month',0.05,true
);

do $$
begin
  if (not (select not enforcement_enabled and kill_switch_enabled
           from public.ai_budget_control where singleton=true)) then
    raise exception 'AI budget control must default to disabled and stopped';
  end if;
  if has_table_privilege('anon','public.ai_budget_reservations','SELECT')
     or has_table_privilege('authenticated','public.ai_budget_ledger','SELECT')
     or has_table_privilege('service_role','public.ai_budget_ledger','INSERT')
     or has_table_privilege('service_role','public.ai_budget_ledger','UPDATE')
     or has_table_privilege('service_role','public.ai_budget_ledger','DELETE')
     or has_function_privilege('anon',
       'public.reserve_ai_budget(uuid,uuid,text,text,text,text,text,numeric)','EXECUTE')
     or has_function_privilege('anon',
       'public.list_ai_budget_reconciliation_candidates(integer)','EXECUTE')
     or not has_function_privilege('service_role',
       'public.list_ai_budget_reconciliation_candidates(integer)','EXECUTE') then
    raise exception 'browser role unexpectedly has AI budget privileges';
  end if;
  begin
    perform * from public.reserve_ai_budget(
      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      current_setting('pwa.test_owner_id')::uuid,'budget-closed-key-0001',
      repeat('e',64),'chat','deepseek','deepseek-flash',0.01
    );
    raise exception 'AI budget RPC must fail closed while disabled';
  exception when sqlstate '55000' then
    if sqlerrm <> 'ai_budget_enforcement_unavailable' then raise; end if;
  end;
end;
$$;

update public.ai_budget_control
set enforcement_enabled=true, kill_switch_enabled=false
where singleton=true;

set local role service_role;

do $$
declare
  v_user uuid := current_setting('pwa.test_owner_id')::uuid;
  v_first uuid;
  v_duplicate uuid;
  v_status text;
  v_count integer;
  v_created boolean;
  v_stale_count integer;
  v_candidate_count integer;
  v_actual numeric;
begin
  select reservation_id,reservation_created into v_first,v_created
  from public.reserve_ai_budget(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',v_user,'budget-test-key-0001',
    repeat('a',64),'chat','deepseek','deepseek-flash',0.02
  );
  if not v_created then raise exception 'new reservation was not marked created'; end if;

  select reservation_id,reservation_created into v_duplicate,v_created
  from public.reserve_ai_budget(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',v_user,'budget-test-key-0001',
    repeat('a',64),'chat','deepseek','deepseek-flash',0.02
  );
  if v_first <> v_duplicate or v_created then
    raise exception 'idempotency did not return the existing reservation';
  end if;

  begin
    perform * from public.reserve_ai_budget(
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',v_user,'budget-test-key-0001',
      repeat('b',64),'chat','deepseek','deepseek-flash',0.02
    );
    raise exception 'idempotency fingerprint conflict was not rejected';
  exception when unique_violation then
    null;
  end;

  v_status := public.settle_ai_budget(v_first,0.01);
  if v_status <> 'settled' then raise exception 'settlement failed'; end if;
  v_status := public.settle_ai_budget(v_first,0.01);
  if v_status <> 'settled' then raise exception 'same settlement was not idempotent'; end if;

  -- A repeated settlement with a different amount must not rewrite the first
  -- accounting result or append a second settlement event.
  begin
    perform public.settle_ai_budget(v_first,0.04);
    raise exception 'conflicting settlement amount was accepted';
  exception when unique_violation then
    null;
  end;
  if (select actual_usd from public.ai_budget_reservations where id=v_first) <> 0.01
     or (select count(*) from public.ai_budget_ledger
         where reservation_id=v_first and event_type='settle') <> 1 then
    raise exception 'conflicting settlement changed the original accounting record';
  end if;

  select reservation_id into v_first
  from public.reserve_ai_budget(
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',v_user,'budget-test-key-0002',
    repeat('c',64),'prompts','deepseek','deepseek-flash',0.03
  );
  if not public.mark_ai_budget_unknown(v_first,'provider_timeout') then
    raise exception 'unknown transition failed';
  end if;
  select count(*) into v_candidate_count
  from public.list_ai_budget_reconciliation_candidates(10)
  where reservation_id = v_first and reservation_status = 'unknown';
  if v_candidate_count <> 1 then
    raise exception 'reconciliation candidate query did not return unknown reservation';
  end if;

  -- Settled spend 0.01 + unknown exposure 0.03 leaves only 0.01 of the 0.05 cap.
  begin
    perform * from public.reserve_ai_budget(
      'dddddddd-dddd-4ddd-8ddd-dddddddddddd',v_user,'budget-test-key-0003',
      repeat('d',64),'chat','deepseek','deepseek-flash',0.02
    );
    raise exception 'platform cap did not reject concurrent exposure';
  exception when raise_exception then
    if sqlerrm <> 'ai_budget_limit_exceeded' then raise; end if;
  end;

  if not public.release_ai_budget_no_charge(v_first,'provider_confirmed_no_charge') then
    raise exception 'confirmed no-charge release failed';
  end if;

  select reservation_id into v_first
  from public.reserve_ai_budget(
    'ffffffff-ffff-4fff-8fff-ffffffffffff',v_user,'budget-test-key-0004',
    repeat('f',64),'chat','deepseek','deepseek-flash',0.01
  );
  v_stale_count := public.mark_stale_ai_budget_reservations_unknown(now() + interval '1 second',10);
  if v_stale_count <> 1 then
    raise exception 'stale reservation was not conservatively marked unknown';
  end if;
  if (select status from public.ai_budget_reservations where id=v_first) <> 'unknown' then
    raise exception 'stale reservation was incorrectly released';
  end if;

  -- A provider overrun must be recorded at its actual amount, never clipped to the reservation.
  select reservation_id into v_first
  from public.reserve_ai_budget(
    '77777777-7777-4777-8777-777777777777',v_user,'budget-test-key-0005',
    repeat('7',64),'chat','deepseek','deepseek-flash',0.005
  );
  v_status := public.settle_ai_budget(v_first,0.08);
  if v_status <> 'settled' then raise exception 'overrun settlement was not recorded'; end if;
  select actual_usd into v_actual
  from public.ai_budget_reservations where id=v_first;
  if v_actual <> 0.08 then
    raise exception 'provider overrun was hidden or clipped: %',v_actual;
  end if;

  -- Actual overrun remains part of platform exposure and blocks new reservations.
  begin
    perform * from public.reserve_ai_budget(
      '66666666-6666-4666-8666-666666666666',v_user,'budget-test-key-0006',
      repeat('6',64),'chat','deepseek','deepseek-flash',0.001
    );
    raise exception 'actual provider overrun did not constrain later reservations';
  exception when sqlstate 'P0001' then
    if sqlerrm <> 'ai_budget_limit_exceeded' then raise; end if;
  end;

  select count(*) into v_count from public.ai_budget_ledger
  where request_id in (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    '77777777-7777-4777-8777-777777777777'
  );
  if v_count <> 9 then raise exception 'unexpected immutable ledger event count: %',v_count; end if;
end;
$$;

rollback;
