-- PWA Studio: private atomic AI budget reservations and immutable ledger.
-- REVIEW ONLY: apply only to disposable CI PostgreSQL until separately approved.
-- Enforcement is disabled and the kill switch is closed by default.

create table if not exists public.ai_budget_control (
  singleton boolean primary key default true check (singleton),
  enforcement_enabled boolean not null default false,
  kill_switch_enabled boolean not null default true,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id) on delete set null
);

insert into public.ai_budget_control(singleton, enforcement_enabled, kill_switch_enabled)
values (true, false, true)
on conflict (singleton) do nothing;

create table if not exists public.ai_budget_policies (
  id uuid primary key default gen_random_uuid(),
  scope_type text not null check (scope_type in ('platform','provider','user')),
  scope_key text not null,
  period_start timestamptz not null,
  period_end timestamptz not null,
  limit_usd numeric(20,10) not null check (limit_usd >= 0),
  enabled boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint ai_budget_policy_period_valid check (period_end > period_start),
  constraint ai_budget_policy_scope_key check (
    (scope_type = 'platform' and scope_key = 'platform') or
    (scope_type = 'provider' and scope_key = lower(scope_key) and length(scope_key) between 1 and 80) or
    (scope_type = 'user' and scope_key ~* '^[0-9a-f-]{36}$')
  ),
  constraint ai_budget_policy_unique_period unique(scope_type, scope_key, period_start, period_end)
);

create index if not exists ai_budget_policies_active_idx
  on public.ai_budget_policies(scope_type, scope_key, period_start, period_end)
  where enabled;

create table if not exists public.ai_budget_reservations (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null unique,
  user_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key text not null check (length(idempotency_key) between 8 and 160),
  request_fingerprint text not null check (request_fingerprint ~ '^[a-f0-9]{64}$'),
  endpoint text not null check (endpoint in ('chat','prompts')),
  provider text not null check (length(provider) between 1 and 80),
  model text not null check (length(model) between 1 and 160),
  status text not null default 'reserved'
    check (status in ('reserved','settled','released','unknown')),
  reserved_usd numeric(20,10) not null check (reserved_usd > 0),
  actual_usd numeric(20,10) check (actual_usd is null or actual_usd >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  settled_at timestamptz,
  constraint ai_budget_reservation_user_idempotency unique(user_id, idempotency_key),
  constraint ai_budget_reservation_terminal_consistency check (
    (status = 'settled' and actual_usd is not null and settled_at is not null) or
    (status <> 'settled' and actual_usd is null and settled_at is null)
  )
);

create index if not exists ai_budget_reservations_user_created_idx
  on public.ai_budget_reservations(user_id, created_at desc);
create index if not exists ai_budget_reservations_open_idx
  on public.ai_budget_reservations(created_at)
  where status in ('reserved','unknown');

create table if not exists public.ai_budget_ledger (
  id bigint generated always as identity primary key,
  reservation_id uuid not null references public.ai_budget_reservations(id) on delete restrict,
  request_id uuid not null,
  user_id uuid not null references auth.users(id) on delete restrict,
  event_type text not null check (event_type in ('reserve','settle','release','unknown')),
  amount_usd numeric(20,10) not null check (amount_usd >= 0),
  safe_reason text check (safe_reason is null or safe_reason ~ '^[a-zA-Z0-9_.-]{1,80}$'),
  created_at timestamptz not null default now(),
  constraint ai_budget_ledger_one_event unique(reservation_id, event_type)
);

create index if not exists ai_budget_ledger_user_created_idx
  on public.ai_budget_ledger(user_id, created_at desc);

alter table public.ai_budget_control enable row level security;
alter table public.ai_budget_policies enable row level security;
alter table public.ai_budget_reservations enable row level security;
alter table public.ai_budget_ledger enable row level security;

revoke all on public.ai_budget_control, public.ai_budget_policies,
  public.ai_budget_reservations, public.ai_budget_ledger from anon, authenticated;
grant select, insert, update on public.ai_budget_control to service_role;
grant select, insert, update on public.ai_budget_policies to service_role;
grant select on public.ai_budget_reservations, public.ai_budget_ledger to service_role;
grant usage, select on sequence public.ai_budget_ledger_id_seq to service_role;

create or replace function public.reserve_ai_budget(
  p_request_id uuid,
  p_user_id uuid,
  p_idempotency_key text,
  p_request_fingerprint text,
  p_endpoint text,
  p_provider text,
  p_model text,
  p_reserved_usd numeric
) returns table(reservation_id uuid, reservation_status text, reserved_usd numeric)
language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_control public.ai_budget_control%rowtype;
  v_existing public.ai_budget_reservations%rowtype;
  v_policy record;
  v_exposure numeric(20,10);
  v_period_spend numeric(20,10);
  v_policy_count integer := 0;
begin
  if p_request_id is null or p_user_id is null
     or p_idempotency_key is null or length(p_idempotency_key) not between 8 and 160
     or p_request_fingerprint is null or p_request_fingerprint !~ '^[a-f0-9]{64}$'
     or p_endpoint not in ('chat','prompts')
     or p_provider is null or length(p_provider) not between 1 and 80
     or p_model is null or length(p_model) not between 1 and 160
     or p_reserved_usd is null or p_reserved_usd <= 0
     or p_reserved_usd::text in ('NaN','Infinity','-Infinity') then
    raise exception 'invalid_ai_budget_reservation' using errcode = '22023';
  end if;

  -- One transaction-wide lock intentionally serializes all reservation decisions.
  -- It is conservative but prevents concurrent users from racing past a global cap.
  perform pg_advisory_xact_lock(728194620031::bigint);

  select * into v_control from public.ai_budget_control where singleton = true for update;
  if not found or not v_control.enforcement_enabled or v_control.kill_switch_enabled then
    raise exception 'ai_budget_enforcement_unavailable' using errcode = '55000';
  end if;

  select * into v_existing from public.ai_budget_reservations r
  where r.user_id = p_user_id and r.idempotency_key = p_idempotency_key;
  if found then
    if v_existing.request_fingerprint <> p_request_fingerprint
       or v_existing.request_id <> p_request_id then
      raise exception 'ai_budget_idempotency_conflict' using errcode = '23505';
    end if;
    return query select v_existing.id, v_existing.status, v_existing.reserved_usd;
    return;
  end if;

  -- An enabled platform policy is mandatory. Provider and user policies are optional.
  for v_policy in
    select p.* from public.ai_budget_policies p
    where p.enabled
      and p.period_start <= now() and p.period_end > now()
      and (
        (p.scope_type = 'platform' and p.scope_key = 'platform') or
        (p.scope_type = 'provider' and p.scope_key = lower(p_provider)) or
        (p.scope_type = 'user' and p.scope_key = p_user_id::text)
      )
    order by case p.scope_type when 'platform' then 1 when 'provider' then 2 else 3 end,
             p.scope_key
    for update
  loop
    v_policy_count := v_policy_count + 1;
    select coalesce(sum(
      case
        when r.status in ('reserved','unknown') then r.reserved_usd
        when r.status = 'settled' then r.actual_usd
        else 0
      end
    ),0) into v_exposure
    from public.ai_budget_reservations r
    where (
      r.created_at >= v_policy.period_start and r.created_at < v_policy.period_end
    ) or r.status in ('reserved','unknown');

    if v_exposure + p_reserved_usd > v_policy.limit_usd then
      raise exception 'ai_budget_limit_exceeded' using errcode = 'P0001';
    end if;
  end loop;

  if v_policy_count = 0 or not exists (
    select 1 from public.ai_budget_policies p
    where p.enabled and p.scope_type = 'platform' and p.scope_key = 'platform'
      and p.period_start <= now() and p.period_end > now()
  ) then
    raise exception 'ai_budget_platform_policy_missing' using errcode = '55000';
  end if;

  insert into public.ai_budget_reservations(
    request_id,user_id,idempotency_key,request_fingerprint,endpoint,provider,model,reserved_usd
  ) values (
    p_request_id,p_user_id,p_idempotency_key,p_request_fingerprint,p_endpoint,
    lower(p_provider),p_model,p_reserved_usd
  ) returning id into reservation_id;

  insert into public.ai_budget_ledger(
    reservation_id,request_id,user_id,event_type,amount_usd
  ) values (reservation_id,p_request_id,p_user_id,'reserve',p_reserved_usd);

  reservation_status := 'reserved';
  reserved_usd := p_reserved_usd;
  return next;
end;
$$;

create or replace function public.settle_ai_budget(
  p_reservation_id uuid, p_actual_usd numeric
) returns text
language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_res public.ai_budget_reservations%rowtype;
begin
  if p_reservation_id is null or p_actual_usd is null or p_actual_usd < 0
     or p_actual_usd::text in ('NaN','Infinity','-Infinity') then
    raise exception 'invalid_ai_budget_settlement' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(728194620031::bigint);
  select * into v_res from public.ai_budget_reservations where id = p_reservation_id for update;
  if not found then return 'not_found'; end if;
  if v_res.status = 'settled' then
    if v_res.actual_usd = p_actual_usd then return 'settled'; end if;
    raise exception 'ai_budget_settlement_conflict' using errcode = '23505';
  end if;
  if v_res.status not in ('reserved','unknown') then
    raise exception 'ai_budget_reservation_not_open' using errcode = '55000';
  end if;
  update public.ai_budget_reservations set status='settled', actual_usd=p_actual_usd,
    settled_at=now(), updated_at=now() where id=p_reservation_id;
  insert into public.ai_budget_ledger(reservation_id,request_id,user_id,event_type,amount_usd)
    values (v_res.id,v_res.request_id,v_res.user_id,'settle',p_actual_usd);
  return 'settled';
end;
$$;

create or replace function public.mark_ai_budget_unknown(
  p_reservation_id uuid, p_safe_reason text
) returns boolean
language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_res public.ai_budget_reservations%rowtype;
begin
  if p_reservation_id is null or p_safe_reason is null
     or p_safe_reason !~ '^[a-zA-Z0-9_.-]{1,80}$' then
    raise exception 'invalid_ai_budget_unknown_reason' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(728194620031::bigint);
  select * into v_res from public.ai_budget_reservations where id=p_reservation_id for update;
  if not found then return false; end if;
  if v_res.status = 'unknown' then return true; end if;
  if v_res.status <> 'reserved' then return false; end if;
  update public.ai_budget_reservations set status='unknown', updated_at=now()
    where id=p_reservation_id;
  insert into public.ai_budget_ledger(reservation_id,request_id,user_id,event_type,amount_usd,safe_reason)
    values (v_res.id,v_res.request_id,v_res.user_id,'unknown',v_res.reserved_usd,p_safe_reason);
  return true;
end;
$$;

create or replace function public.release_ai_budget_no_charge(
  p_reservation_id uuid, p_safe_reason text
) returns boolean
language plpgsql security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare v_res public.ai_budget_reservations%rowtype;
begin
  if p_reservation_id is null or p_safe_reason is null
     or p_safe_reason !~ '^[a-zA-Z0-9_.-]{1,80}$' then
    raise exception 'invalid_ai_budget_release_reason' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(728194620031::bigint);
  select * into v_res from public.ai_budget_reservations where id=p_reservation_id for update;
  if not found then return false; end if;
  if v_res.status = 'released' then return true; end if;
  if v_res.status not in ('reserved','unknown') then return false; end if;
  update public.ai_budget_reservations set status='released', updated_at=now()
    where id=p_reservation_id;
  insert into public.ai_budget_ledger(reservation_id,request_id,user_id,event_type,amount_usd,safe_reason)
    values (v_res.id,v_res.request_id,v_res.user_id,'release',v_res.reserved_usd,p_safe_reason);
  return true;
end;
$$;

revoke all on function public.reserve_ai_budget(uuid,uuid,text,text,text,text,text,numeric) from public, anon, authenticated;
revoke all on function public.settle_ai_budget(uuid,numeric) from public, anon, authenticated;
revoke all on function public.mark_ai_budget_unknown(uuid,text) from public, anon, authenticated;
revoke all on function public.release_ai_budget_no_charge(uuid,text) from public, anon, authenticated;
grant execute on function public.reserve_ai_budget(uuid,uuid,text,text,text,text,text,numeric) to service_role;
grant execute on function public.settle_ai_budget(uuid,numeric) to service_role;
grant execute on function public.mark_ai_budget_unknown(uuid,text) to service_role;
grant execute on function public.release_ai_budget_no_charge(uuid,text) to service_role;

comment on table public.ai_budget_control is
  'Backend-only global AI budget switch. New installs default to disabled enforcement and closed kill switch.';
comment on table public.ai_budget_policies is
  'Backend-only approved USD spending policies. No numerical policy is seeded.';
comment on table public.ai_budget_reservations is
  'Private idempotent pre-provider reservations. Unknown outcomes remain counted.';
comment on table public.ai_budget_ledger is
  'Append-only audit events for reserve, settlement, release, and unknown outcomes.';
comment on function public.reserve_ai_budget(uuid,uuid,text,text,text,text,text,numeric) is
  'Serializes reservation decisions and enforces active platform/provider/user caps. Backend service_role only.';
