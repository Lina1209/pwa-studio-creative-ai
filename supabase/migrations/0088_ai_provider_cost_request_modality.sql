-- Add immutable request modality to the shared synchronous AI USD reservation ledger.
-- Existing reservations are classified as text; no historical cost is rewritten.
alter table public.ai_provider_cost_reservations
  add column if not exists request_modality text not null default 'text';

alter table public.ai_provider_cost_reservations
  drop constraint if exists ai_provider_cost_reservations_modality_check;
alter table public.ai_provider_cost_reservations
  add constraint ai_provider_cost_reservations_modality_check
  check (request_modality in ('text', 'vision'));

create index if not exists ai_provider_cost_reservations_modality_created_idx
  on public.ai_provider_cost_reservations(request_modality, created_at desc);

create or replace function public.prevent_ai_provider_cost_modality_change()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  if old.request_modality is distinct from new.request_modality then
    raise exception 'AI provider cost request modality is immutable'
      using errcode = '23514';
  end if;
  return new;
end;
$$;

drop trigger if exists ai_provider_cost_modality_immutable
  on public.ai_provider_cost_reservations;
create trigger ai_provider_cost_modality_immutable
before update on public.ai_provider_cost_reservations
for each row execute function public.prevent_ai_provider_cost_modality_change();

-- Versioned RPC avoids changing the existing PostgREST function signature.
-- Both text and Vision reservations lock the same global policy row and provider
-- budget row, and therefore consume the exact same global/provider USD budgets.
create or replace function public.reserve_ai_provider_cost_v2(
  p_request_id uuid,
  p_user_id uuid,
  p_provider text,
  p_model text,
  p_reserved_cost_usd numeric,
  p_request_modality text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_global public.ai_provider_budget_policy%rowtype;
  v_provider public.ai_provider_daily_budgets%rowtype;
  v_existing public.ai_provider_cost_reservations%rowtype;
  v_global_spent numeric(20,10);
  v_provider_spent numeric(20,10);
  v_outstanding numeric(20,10);
  v_provider_outstanding numeric(20,10);
  v_day_start timestamptz := date_trunc('day', now() at time zone 'UTC') at time zone 'UTC';
begin
  if p_request_id is null or p_user_id is null
     or p_provider is null or p_provider not in ('deepseek', 'gemini')
     or p_model is null or length(p_model) not between 1 and 200
     or p_reserved_cost_usd is null or p_reserved_cost_usd <= 0
     or p_reserved_cost_usd > 1000000000
     or p_request_modality is null
     or p_request_modality not in ('text', 'vision') then
    raise exception 'Invalid synchronous AI cost reservation' using errcode = '22023';
  end if;

  -- Global row lock serializes every provider and modality against one budget.
  select * into v_global from public.ai_provider_budget_policy
   where singleton = true for update;
  if not found or not v_global.enabled then
    return jsonb_build_object('admitted', false, 'reason', 'global_budget_disabled');
  end if;

  select * into v_provider from public.ai_provider_daily_budgets
   where provider = p_provider for update;
  if not found or not v_provider.enabled then
    return jsonb_build_object('admitted', false, 'reason', 'provider_budget_disabled');
  end if;

  select * into v_existing from public.ai_provider_cost_reservations
   where request_id = p_request_id for update;
  if found then
    if v_existing.user_id <> p_user_id
       or v_existing.provider <> p_provider
       or v_existing.model <> p_model
       or v_existing.reserved_cost_usd <> p_reserved_cost_usd
       or v_existing.request_modality <> p_request_modality then
      raise exception 'AI provider cost reservation idempotency conflict'
        using errcode = '23505';
    end if;
    return jsonb_build_object('admitted', false, 'reason', 'duplicate_reservation');
  end if;

  select coalesce(sum(actual_estimated_cost_usd), 0) into v_global_spent
    from public.ai_provider_cost_reservations
   where status = 'settled' and settled_at >= v_day_start;
  select coalesce(sum(actual_estimated_cost_usd), 0) into v_provider_spent
    from public.ai_provider_cost_reservations
   where provider = p_provider and status = 'settled' and settled_at >= v_day_start;
  select coalesce(sum(reserved_cost_usd), 0) into v_outstanding
    from public.ai_provider_cost_reservations
   where status in ('reserved', 'unknown');
  select coalesce(sum(reserved_cost_usd), 0) into v_provider_outstanding
    from public.ai_provider_cost_reservations
   where provider = p_provider and status in ('reserved', 'unknown');

  if v_global_spent + v_outstanding + p_reserved_cost_usd > v_global.global_daily_budget_usd then
    return jsonb_build_object('admitted', false, 'reason', 'global_daily_budget_reached');
  end if;
  if v_provider_spent + v_provider_outstanding + p_reserved_cost_usd > v_provider.daily_budget_usd then
    return jsonb_build_object('admitted', false, 'reason', 'provider_daily_budget_reached');
  end if;
  if v_outstanding + p_reserved_cost_usd > v_global.max_outstanding_reserved_usd then
    return jsonb_build_object('admitted', false, 'reason', 'outstanding_exposure_limit');
  end if;

  insert into public.ai_provider_cost_reservations(
    request_id, user_id, provider, model, reserved_cost_usd, request_modality, status
  ) values (
    p_request_id, p_user_id, p_provider, p_model, p_reserved_cost_usd, p_request_modality, 'reserved'
  );

  return jsonb_build_object(
    'admitted', true,
    'reserved_cost_usd', p_reserved_cost_usd,
    'request_modality', p_request_modality
  );
end;
$$;

-- Preserve compatibility for existing backend versions: old calls are text requests.
create or replace function public.reserve_ai_provider_cost(
  p_request_id uuid,
  p_user_id uuid,
  p_provider text,
  p_model text,
  p_reserved_cost_usd numeric
)
returns jsonb
language sql
security definer
set search_path = pg_catalog, public
as $$
  select public.reserve_ai_provider_cost_v2(
    p_request_id, p_user_id, p_provider, p_model, p_reserved_cost_usd, 'text'
  );
$$;

revoke all on function public.reserve_ai_provider_cost_v2(uuid, uuid, text, text, numeric, text)
  from public, anon, authenticated;
revoke all on function public.reserve_ai_provider_cost(uuid, uuid, text, text, numeric)
  from public, anon, authenticated;
grant execute on function public.reserve_ai_provider_cost_v2(uuid, uuid, text, text, numeric, text)
  to service_role;
grant execute on function public.reserve_ai_provider_cost(uuid, uuid, text, text, numeric)
  to service_role;

comment on column public.ai_provider_cost_reservations.request_modality is
  'Immutable server-classified request modality (text or vision); all modalities share the same global and provider USD budgets.';
comment on function public.reserve_ai_provider_cost_v2(uuid, uuid, text, text, numeric, text) is
  'Atomically reserves shared global/provider USD exposure and records immutable text/Vision modality. Service-role only.';
