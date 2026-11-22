-- Atomic USD exposure controls for synchronous DeepSeek/Gemini calls.
-- Limits are conservative initial guardrails; provider invoice reconciliation is separate.
-- All monetary amounts are USD. Unknown outcomes keep their full reservation locked.

create table if not exists public.ai_provider_budget_policy (
  singleton boolean primary key default true check (singleton),
  enabled boolean not null default true,
  global_daily_budget_usd numeric(20,10) not null check (global_daily_budget_usd > 0),
  max_outstanding_reserved_usd numeric(20,10) not null check (max_outstanding_reserved_usd > 0),
  updated_at timestamptz not null default now(),
  updated_by text not null default session_user
);

insert into public.ai_provider_budget_policy(
  singleton, enabled, global_daily_budget_usd, max_outstanding_reserved_usd
) values (true, true, 2.00, 0.50)
on conflict (singleton) do nothing;

create table if not exists public.ai_provider_daily_budgets (
  provider text primary key check (provider in ('deepseek', 'gemini')),
  daily_budget_usd numeric(20,10) not null check (daily_budget_usd > 0),
  enabled boolean not null default true,
  updated_at timestamptz not null default now(),
  updated_by text not null default session_user
);

insert into public.ai_provider_daily_budgets(provider, daily_budget_usd, enabled)
values ('deepseek', 1.00, true), ('gemini', 1.00, true)
on conflict (provider) do nothing;

create table if not exists public.ai_provider_cost_reservations (
  request_id uuid primary key,
  user_id uuid not null references auth.users(id) on delete restrict,
  provider text not null check (provider in ('deepseek', 'gemini')),
  model text not null check (length(model) between 1 and 200),
  reserved_cost_usd numeric(20,10) not null check (reserved_cost_usd > 0),
  actual_estimated_cost_usd numeric(20,10) check (actual_estimated_cost_usd is null or actual_estimated_cost_usd >= 0),
  status text not null default 'reserved'
    check (status in ('reserved', 'unknown', 'settled', 'released')),
  cost_source text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  settled_at timestamptz,
  resolution_note text,
  constraint ai_provider_cost_reservation_state_check check (
    (status in ('reserved', 'unknown') and settled_at is null)
    or (status in ('settled', 'released') and settled_at is not null)
  )
);

create index if not exists ai_provider_cost_reservations_status_created_idx
  on public.ai_provider_cost_reservations(status, created_at);
create index if not exists ai_provider_cost_reservations_provider_created_idx
  on public.ai_provider_cost_reservations(provider, created_at);

alter table public.ai_provider_budget_policy enable row level security;
alter table public.ai_provider_daily_budgets enable row level security;
alter table public.ai_provider_cost_reservations enable row level security;
revoke all on public.ai_provider_budget_policy from public, anon, authenticated;
revoke all on public.ai_provider_daily_budgets from public, anon, authenticated;
revoke all on public.ai_provider_cost_reservations from public, anon, authenticated;
revoke insert, update, delete, truncate on public.ai_provider_budget_policy from service_role;
revoke insert, update, delete, truncate on public.ai_provider_daily_budgets from service_role;
revoke insert, update, delete, truncate on public.ai_provider_cost_reservations from service_role;
grant select on public.ai_provider_budget_policy to service_role;
grant select on public.ai_provider_daily_budgets to service_role;
grant select on public.ai_provider_cost_reservations to service_role;

create or replace function public.reserve_ai_provider_cost(
  p_request_id uuid,
  p_user_id uuid,
  p_provider text,
  p_model text,
  p_reserved_cost_usd numeric
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
  v_day_start timestamptz := date_trunc('day', now() at time zone 'UTC') at time zone 'UTC';
begin
  if p_request_id is null or p_user_id is null
     or p_provider is null or p_provider not in ('deepseek', 'gemini')
     or p_model is null or length(p_model) not between 1 and 200
     or p_reserved_cost_usd is null or p_reserved_cost_usd <= 0
     or p_reserved_cost_usd > 1000000000 then
    raise exception 'Invalid synchronous AI cost reservation' using errcode = '22023';
  end if;

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
    if v_existing.user_id <> p_user_id or v_existing.provider <> p_provider
       or v_existing.model <> p_model or v_existing.reserved_cost_usd <> p_reserved_cost_usd then
      raise exception 'AI provider cost reservation idempotency conflict' using errcode = '23505';
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

  if v_global_spent + v_outstanding + p_reserved_cost_usd > v_global.global_daily_budget_usd then
    return jsonb_build_object('admitted', false, 'reason', 'global_daily_budget_reached');
  end if;
  if v_provider_spent + (
      select coalesce(sum(reserved_cost_usd), 0)
        from public.ai_provider_cost_reservations
       where provider = p_provider and status in ('reserved', 'unknown')
     ) + p_reserved_cost_usd > v_provider.daily_budget_usd then
    return jsonb_build_object('admitted', false, 'reason', 'provider_daily_budget_reached');
  end if;
  if v_outstanding + p_reserved_cost_usd > v_global.max_outstanding_reserved_usd then
    return jsonb_build_object('admitted', false, 'reason', 'outstanding_exposure_limit');
  end if;

  insert into public.ai_provider_cost_reservations(
    request_id, user_id, provider, model, reserved_cost_usd, status
  ) values (p_request_id, p_user_id, p_provider, p_model, p_reserved_cost_usd, 'reserved');

  return jsonb_build_object('admitted', true, 'reserved_cost_usd', p_reserved_cost_usd);
end;
$$;

create or replace function public.settle_ai_provider_cost(
  p_request_id uuid,
  p_actual_estimated_cost_usd numeric,
  p_cost_source text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_row public.ai_provider_cost_reservations%rowtype;
begin
  if p_request_id is null
     or (p_actual_estimated_cost_usd is not null and
         (p_actual_estimated_cost_usd < 0 or p_actual_estimated_cost_usd > 1000000000))
     or (p_cost_source is not null and length(p_cost_source) > 80) then
    raise exception 'Invalid AI provider cost settlement' using errcode = '22023';
  end if;

  perform 1 from public.ai_provider_budget_policy where singleton = true for update;
  select * into v_row from public.ai_provider_cost_reservations
   where request_id = p_request_id for update;
  if not found then
    return false;
  end if;
  if v_row.status in ('settled', 'unknown') then
    return true;
  end if;
  if v_row.status <> 'reserved' then
    return false;
  end if;

  if p_actual_estimated_cost_usd is null or p_cost_source is null then
    update public.ai_provider_cost_reservations
       set status = 'unknown', cost_source = 'unknown',
           updated_at = now(),
           resolution_note = 'Provider outcome received without complete token usage; full reservation retained.'
     where request_id = p_request_id;
  else
    update public.ai_provider_cost_reservations
       set status = 'settled',
           actual_estimated_cost_usd = p_actual_estimated_cost_usd,
           cost_source = p_cost_source,
           settled_at = now(), updated_at = now(),
           resolution_note = 'Settled using conservative server-side peak token pricing; not an invoice.'
     where request_id = p_request_id;
  end if;
  return true;
end;
$$;

-- Explicit operator reconciliation for unknown reservations. This is callable only
-- with service_role and requires a written audit note. No timeout auto-releases funds.
create or replace function public.resolve_ai_provider_cost_reservation(
  p_request_id uuid,
  p_resolution text,
  p_actual_estimated_cost_usd numeric,
  p_note text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_row public.ai_provider_cost_reservations%rowtype;
begin
  if p_request_id is null
     or p_resolution is null or p_resolution not in ('confirm_no_charge', 'record_estimated_cost')
     or p_note is null or length(btrim(p_note)) not between 8 and 1000
     or (p_resolution = 'confirm_no_charge' and p_actual_estimated_cost_usd is not null)
     or (p_resolution = 'record_estimated_cost' and
         (p_actual_estimated_cost_usd is null or p_actual_estimated_cost_usd < 0
          or p_actual_estimated_cost_usd > 1000000000)) then
    raise exception 'Invalid AI cost reservation reconciliation' using errcode = '22023';
  end if;

  perform 1 from public.ai_provider_budget_policy where singleton = true for update;
  select * into v_row from public.ai_provider_cost_reservations
   where request_id = p_request_id for update;
  if not found or v_row.status <> 'unknown' then
    return false;
  end if;

  if p_resolution = 'confirm_no_charge' then
    update public.ai_provider_cost_reservations
       set status = 'released', settled_at = now(), updated_at = now(),
           resolution_note = btrim(p_note), cost_source = 'operator_confirmed_no_charge'
     where request_id = p_request_id;
  else
    update public.ai_provider_cost_reservations
       set status = 'settled', actual_estimated_cost_usd = p_actual_estimated_cost_usd,
           settled_at = now(), updated_at = now(),
           resolution_note = btrim(p_note), cost_source = 'operator_reconciled_estimate'
     where request_id = p_request_id;
  end if;
  return true;
end;
$$;

revoke all on function public.reserve_ai_provider_cost(uuid, uuid, text, text, numeric)
  from public, anon, authenticated;
revoke all on function public.settle_ai_provider_cost(uuid, numeric, text)
  from public, anon, authenticated;
revoke all on function public.resolve_ai_provider_cost_reservation(uuid, text, numeric, text)
  from public, anon, authenticated;
grant execute on function public.reserve_ai_provider_cost(uuid, uuid, text, text, numeric)
  to service_role;
grant execute on function public.settle_ai_provider_cost(uuid, numeric, text)
  to service_role;
grant execute on function public.resolve_ai_provider_cost_reservation(uuid, text, numeric, text)
  to service_role;

-- The AI usage ledger must accept the three Mini Movie Studio AI operations.
alter table public.ai_usage drop constraint if exists ai_usage_endpoint_check;
alter table public.ai_usage add constraint ai_usage_endpoint_check
  check (endpoint in ('chat', 'prompts', 'movie_script', 'movie_director', 'movie_storyboard'));

comment on table public.ai_provider_cost_reservations is
  'Atomic pre-call USD exposure reservations for synchronous AI. Unknown provider outcomes retain the reserve until audited operator reconciliation.';
comment on function public.reserve_ai_provider_cost(uuid, uuid, text, text, numeric) is
  'Serializes synchronous AI admission against global and per-provider UTC-day USD budgets and outstanding exposure; all limits are checked before provider network calls.';
