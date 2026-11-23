-- Transactional integration checks for modality-aware shared AI cost reservations.
-- Run after migrations 0050 and 0088 in a disposable PostgreSQL test database.
begin;

do $$
declare
  v_user uuid := '8c1a9a44-47b8-4d58-9f9c-30b0f55e9a88';
  v_text_request uuid := '9d19c9c8-4e51-43c4-9f1b-1bff3f49a101';
  v_vision_request uuid := '9d19c9c8-4e51-43c4-9f1b-1bff3f49a102';
  v_text_request_2 uuid := '9d19c9c8-4e51-43c4-9f1b-1bff3f49a104';
  v_vision_request_2 uuid := '9d19c9c8-4e51-43c4-9f1b-1bff3f49a105';
  v_text_request_3 uuid := '9d19c9c8-4e51-43c4-9f1b-1bff3f49a106';
  v_vision_request_3 uuid := '9d19c9c8-4e51-43c4-9f1b-1bff3f49a107';
  v_result jsonb;
  v_count integer;
  v_state text;
  v_modality text;
  v_failed boolean;
begin
  insert into auth.users(id) values (v_user) on conflict (id) do nothing;

  -- Isolate this transaction from unrelated reservations in the disposable test DB.
  delete from public.ai_provider_cost_reservations;
  update public.ai_provider_budget_policy
     set enabled = true, global_daily_budget_usd = 1.00,
         max_outstanding_reserved_usd = 1.00, updated_at = now();
  update public.ai_provider_daily_budgets
     set enabled = true, daily_budget_usd = 1.00, updated_at = now()
   where provider = 'deepseek';

  v_result := public.reserve_ai_provider_cost_v2(
    v_text_request, v_user, 'deepseek', 'deepseek-flash', 0.60, 'text'
  );
  if coalesce((v_result ->> 'admitted')::boolean, false) is not true then
    raise exception 'Text reservation should be admitted: %', v_result;
  end if;

  -- Text exposure is already 0.60; Vision must share the same 1.00 USD ceiling.
  v_result := public.reserve_ai_provider_cost_v2(
    v_vision_request, v_user, 'deepseek', 'deepseek-flash', 0.60, 'vision'
  );
  if coalesce((v_result ->> 'admitted')::boolean, true) is not false
     or coalesce(v_result ->> 'reason', '') <> 'global_daily_budget_reached' then
    raise exception 'Vision reservation must share the text global budget: %', v_result;
  end if;

  -- The same idempotency key cannot be replayed under a different modality.
  v_failed := false;
  begin
    perform public.reserve_ai_provider_cost_v2(
      v_text_request, v_user, 'deepseek', 'deepseek-flash', 0.60, 'vision'
    );
  exception when sqlstate '23505' then
    v_failed := true;
  end;
  if not v_failed then
    raise exception 'Changing modality on an existing request must fail';
  end if;

  -- The immutable modality cannot be edited even by a privileged SQL writer.
  v_failed := false;
  begin
    update public.ai_provider_cost_reservations
       set request_modality = 'vision'
     where request_id = v_text_request;
  exception when check_violation then
    v_failed := true;
  end;
  if not v_failed then
    raise exception 'Request modality must be immutable';
  end if;

  -- A settlement must name the same modality as the original reservation.
  v_failed := false;
  begin
    perform public.settle_ai_provider_cost_v2(
      v_text_request, 'vision', 0.10, 'server_peak_price_estimate'
    );
  exception when sqlstate '23505' then
    v_failed := true;
  end;
  if not v_failed then
    raise exception 'Cross-modality settlement must fail';
  end if;

  -- Correct modality settles normally and retains its classification.
  perform public.settle_ai_provider_cost_v2(
    v_text_request, 'text', 0.10, 'server_peak_price_estimate'
  );
  select request_modality, status into v_modality, v_state
    from public.ai_provider_cost_reservations
   where request_id = v_text_request;
  if v_modality <> 'text' or v_state <> 'settled' then
    raise exception 'Text settlement must preserve modality and settle state';
  end if;

  select count(*) into v_count
    from public.ai_provider_cost_reservations
   where request_modality in ('text', 'vision');
  if v_count <> 1 then
    raise exception 'Expected exactly one committed reservation in this test transaction, got %', v_count;
  end if;

  -- Provider-specific daily budget is also shared across modalities.
  delete from public.ai_provider_cost_reservations;
  update public.ai_provider_budget_policy
     set global_daily_budget_usd = 10.00,
         max_outstanding_reserved_usd = 10.00, updated_at = now();
  update public.ai_provider_daily_budgets
     set daily_budget_usd = 1.00, updated_at = now()
   where provider = 'deepseek';
  v_result := public.reserve_ai_provider_cost_v2(
    v_text_request_2, v_user, 'deepseek', 'deepseek-flash', 0.60, 'text'
  );
  if coalesce((v_result ->> 'admitted')::boolean, false) is not true then
    raise exception 'Text reservation should fit provider budget: %', v_result;
  end if;
  v_result := public.reserve_ai_provider_cost_v2(
    v_vision_request_2, v_user, 'deepseek', 'deepseek-flash', 0.60, 'vision'
  );
  if coalesce((v_result ->> 'admitted')::boolean, true) is not false
     or coalesce(v_result ->> 'reason', '') <> 'provider_daily_budget_reached' then
    raise exception 'Vision reservation must share the provider daily budget: %', v_result;
  end if;

  -- Outstanding exposure is likewise modality-independent.
  delete from public.ai_provider_cost_reservations;
  update public.ai_provider_daily_budgets
     set daily_budget_usd = 10.00, updated_at = now()
   where provider = 'deepseek';
  update public.ai_provider_budget_policy
     set max_outstanding_reserved_usd = 0.70, updated_at = now();
  v_result := public.reserve_ai_provider_cost_v2(
    v_text_request_3, v_user, 'deepseek', 'deepseek-flash', 0.60, 'text'
  );
  if coalesce((v_result ->> 'admitted')::boolean, false) is not true then
    raise exception 'Text reservation should fit outstanding exposure cap: %', v_result;
  end if;
  v_result := public.reserve_ai_provider_cost_v2(
    v_vision_request_3, v_user, 'deepseek', 'deepseek-flash', 0.20, 'vision'
  );
  if coalesce((v_result ->> 'admitted')::boolean, true) is not false
     or coalesce(v_result ->> 'reason', '') <> 'outstanding_exposure_limit' then
    raise exception 'Vision reservation must share outstanding exposure cap: %', v_result;
  end if;
end;
$$;

rollback;
