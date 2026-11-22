-- Audited administrator controls for synchronous AI USD budgets.
-- Functions are SECURITY DEFINER but executable only by service_role.
create or replace function public.update_ai_provider_global_budget(
  p_enabled boolean, p_global_daily_budget_usd numeric, p_max_outstanding_reserved_usd numeric
) returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v public.ai_provider_budget_policy%rowtype;
begin
  if p_enabled is null or p_global_daily_budget_usd is null or p_global_daily_budget_usd <= 0
     or p_global_daily_budget_usd > 1000000000 or p_max_outstanding_reserved_usd is null
     or p_max_outstanding_reserved_usd <= 0 or p_max_outstanding_reserved_usd > p_global_daily_budget_usd then
    raise exception 'Invalid global AI budget settings' using errcode='22023';
  end if;
  select * into v from public.ai_provider_budget_policy where singleton=true for update;
  if not found then raise exception 'Global AI budget policy missing'; end if;
  update public.ai_provider_budget_policy set enabled=p_enabled,
    global_daily_budget_usd=p_global_daily_budget_usd,
    max_outstanding_reserved_usd=p_max_outstanding_reserved_usd,
    updated_at=now(),updated_by='service_role' where singleton=true returning * into v;
  return jsonb_build_object('enabled',v.enabled,'global_daily_budget_usd',v.global_daily_budget_usd,
    'max_outstanding_reserved_usd',v.max_outstanding_reserved_usd,'updated_at',v.updated_at);
end; $$;

create or replace function public.update_ai_provider_daily_budget(
  p_provider text, p_enabled boolean, p_daily_budget_usd numeric
) returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare v public.ai_provider_daily_budgets%rowtype;
begin
  if p_provider is null or p_provider not in ('deepseek','gemini') or p_enabled is null
     or p_daily_budget_usd is null or p_daily_budget_usd <= 0 or p_daily_budget_usd > 1000000000 then
    raise exception 'Invalid provider AI budget settings' using errcode='22023';
  end if;
  select * into v from public.ai_provider_daily_budgets where provider=p_provider for update;
  if not found then raise exception 'Provider AI budget policy missing'; end if;
  update public.ai_provider_daily_budgets set enabled=p_enabled,daily_budget_usd=p_daily_budget_usd,
    updated_at=now(),updated_by='service_role' where provider=p_provider returning * into v;
  return jsonb_build_object('provider',v.provider,'enabled',v.enabled,
    'daily_budget_usd',v.daily_budget_usd,'updated_at',v.updated_at);
end; $$;

revoke all on function public.update_ai_provider_global_budget(boolean,numeric,numeric) from public,anon,authenticated;
revoke all on function public.update_ai_provider_daily_budget(text,boolean,numeric) from public,anon,authenticated;
grant execute on function public.update_ai_provider_global_budget(boolean,numeric,numeric) to service_role;
grant execute on function public.update_ai_provider_daily_budget(text,boolean,numeric) to service_role;

comment on function public.update_ai_provider_global_budget(boolean,numeric,numeric) is
  'Updates global synchronous AI USD limits. Callable only by backend service_role; admin authorization and audit are enforced by the API.';
comment on function public.update_ai_provider_daily_budget(text,boolean,numeric) is
  'Updates one DeepSeek/Gemini daily USD limit and enable switch. Callable only by backend service_role.';
