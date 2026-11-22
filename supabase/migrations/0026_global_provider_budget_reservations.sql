-- PWA Studio: global, atomic provider spend budgets and durable reservations.
-- No production amounts are seeded. Until an operator configures BOTH limits,
-- billable provider admission remains disabled (fail closed).
-- Apply after 0025_provider_cost_budget_admission.sql.

create table if not exists public.provider_budget_policy (
  singleton boolean primary key default true check (singleton),
  enabled boolean not null default false,
  daily_budget_usd numeric(20,10),
  max_outstanding_reserved_usd numeric(20,10),
  updated_at timestamptz not null default now(),
  updated_by text not null default session_user,
  constraint provider_budget_policy_daily_positive
    check (daily_budget_usd is null or daily_budget_usd > 0),
  constraint provider_budget_policy_exposure_positive
    check (max_outstanding_reserved_usd is null or max_outstanding_reserved_usd > 0),
  constraint provider_budget_policy_enabled_complete
    check (
      (enabled = false)
      or (daily_budget_usd is not null and max_outstanding_reserved_usd is not null)
    )
);

insert into public.provider_budget_policy(singleton, enabled)
values (true, false)
on conflict (singleton) do nothing;

alter table public.provider_budget_policy enable row level security;
revoke all on public.provider_budget_policy from public, anon, authenticated;
revoke insert, update, delete, truncate on public.provider_budget_policy from service_role;
grant select on public.provider_budget_policy to service_role;

create table if not exists public.generation_provider_cost_reservations (
  job_id uuid primary key,
  user_id uuid not null,
  provider text not null check (length(provider) between 1 and 100),
  model text not null check (length(model) between 1 and 200),
  operation_key text not null check (length(operation_key) between 8 and 200),
  reserved_cost_usd numeric(20,10) not null check (reserved_cost_usd > 0),
  status text not null default 'reserved'
    check (status in ('reserved', 'unknown', 'settled', 'released')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  settled_at timestamptz,
  released_at timestamptz,
  resolution text,
  resolution_note text,
  resolved_by text,
  constraint generation_provider_cost_reservations_job_owner_fkey
    foreign key (job_id, user_id)
    references public.generation_jobs(id, user_id) on delete restrict,
  constraint generation_provider_cost_reservations_resolution_check
    check (
      (status in ('reserved', 'unknown') and settled_at is null and released_at is null)
      or (status = 'settled' and settled_at is not null and released_at is null)
      or (status = 'released' and released_at is not null and settled_at is null)
    ),
  constraint generation_provider_cost_reservations_resolution_text_check
    check (
      (resolution is null and resolution_note is null and resolved_by is null)
      or (
        resolution in ('provider_cost_recorded', 'operator_confirmed_no_charge', 'operator_reconciled_cost')
        and resolution_note is not null and length(resolution_note) between 8 and 1000
        and resolved_by is not null and length(resolved_by) between 1 and 120
      )
    )
);

create index if not exists generation_provider_cost_reservations_status_idx
  on public.generation_provider_cost_reservations(status, created_at);

-- Preserve existing cost evidence during rollout. Jobs with a valid
-- signed USD ceiling receive a reservation sized to that ceiling; any prior
-- unknown usage keeps it in the unknown state. Orphan unknown evidence without
-- a valid ceiling remains a global admission blocker until operator repair.
with evidence as (
  select
    job.id as job_id,
    job.user_id,
    job.provider,
    job.model,
    event.cost_source,
    event.created_at,
    case
      when (job.pricing_snapshot ->> 'maximum_provider_cost_usd')
           ~ '^(0|[1-9][0-9]{0,9})([.][0-9]{1,10})?$'
      then (job.pricing_snapshot ->> 'maximum_provider_cost_usd')::numeric(20,10)
      else null
    end as reserved_cost_usd
  from public.generation_provider_cost_events event
  join public.generation_jobs job on job.id = event.job_id
)
insert into public.generation_provider_cost_reservations(
  job_id, user_id, provider, model, operation_key, reserved_cost_usd,
  status, created_at, settled_at
)
select
  evidence.job_id,
  evidence.user_id,
  evidence.provider,
  evidence.model,
  evidence.job_id::text,
  evidence.reserved_cost_usd,
  case when bool_or(evidence.cost_source = 'unknown') then 'unknown' else 'settled' end,
  min(evidence.created_at),
  case when bool_or(evidence.cost_source = 'unknown') then null else max(evidence.created_at) end
from evidence
where evidence.reserved_cost_usd is not null
  and evidence.reserved_cost_usd > 0
group by evidence.job_id, evidence.user_id, evidence.provider, evidence.model,
         evidence.reserved_cost_usd
on conflict (job_id) do nothing;

alter table public.generation_provider_cost_reservations enable row level security;
revoke all on public.generation_provider_cost_reservations from public, anon, authenticated;
revoke insert, update, delete, truncate on public.generation_provider_cost_reservations from service_role;
grant select on public.generation_provider_cost_reservations to service_role;

-- The operator-facing configuration RPC is the only supported policy write path.
create or replace function public.configure_provider_budget_policy(
  p_daily_budget_usd numeric,
  p_max_outstanding_reserved_usd numeric
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if (p_daily_budget_usd is not null and
      (p_daily_budget_usd <= 0 or p_daily_budget_usd > 1000000000))
     or (p_max_outstanding_reserved_usd is not null and
      (p_max_outstanding_reserved_usd <= 0 or p_max_outstanding_reserved_usd > 1000000000)) then
    raise exception 'Provider budget policy values must be positive bounded USD amounts'
      using errcode = '22023';
  end if;

  update public.provider_budget_policy
     set daily_budget_usd = p_daily_budget_usd,
         max_outstanding_reserved_usd = p_max_outstanding_reserved_usd,
         enabled = p_daily_budget_usd is not null
                   and p_max_outstanding_reserved_usd is not null,
         updated_at = now(),
         updated_by = session_user
   where singleton = true;

  return found;
end;
$$;

revoke all on function public.configure_provider_budget_policy(numeric, numeric)
  from public, anon, authenticated;
grant execute on function public.configure_provider_budget_policy(numeric, numeric)
  to service_role;

-- Cost evidence settles a reservation only when the provider reports a known
-- amount. Unknown evidence keeps the full reserve locked until operator review.
create or replace function public.sync_generation_provider_cost_reservation()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  update public.generation_provider_cost_reservations
     set status = case when new.cost_source = 'unknown' then 'unknown' else 'settled' end,
         settled_at = case when new.cost_source = 'unknown' then null else now() end,
         released_at = null,
         updated_at = now(),
         resolution = 'provider_cost_recorded',
         resolution_note = case
           when new.cost_source = 'unknown'
             then 'Provider usage was recorded but the charge amount remains unknown; reservation retained.'
           else 'Known provider cost evidence was recorded; reservation settled.'
         end,
         resolved_by = 'provider-cost-ledger'
   where job_id = new.job_id;

  return new;
end;
$$;

drop trigger if exists generation_provider_cost_reservation_sync
  on public.generation_provider_cost_events;
create trigger generation_provider_cost_reservation_sync
after insert on public.generation_provider_cost_events
for each row execute function public.sync_generation_provider_cost_reservation();

-- Replace the per-job-only gate with a global serialized admission transaction.
-- The singleton policy row is locked first, so separate jobs cannot race through
-- the daily or concurrent-exposure limits.
create or replace function public.authorize_generation_provider_operation(
  p_job_id uuid,
  p_worker_id text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_policy public.provider_budget_policy%rowtype;
  v_job public.generation_jobs%rowtype;
  v_budget_text text;
  v_job_cap numeric(20,10);
  v_daily_spent numeric(20,10);
  v_outstanding numeric(20,10);
  v_existing public.generation_provider_cost_reservations%rowtype;
begin
  if p_job_id is null or p_worker_id is null
     or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'Invalid provider budget admission identity' using errcode = '22023';
  end if;

  select * into v_policy
    from public.provider_budget_policy
   where singleton = true
   for update;

  if not found or not v_policy.enabled
     or v_policy.daily_budget_usd is null
     or v_policy.max_outstanding_reserved_usd is null then
    return false;
  end if;

  select * into v_job
    from public.generation_jobs
   where id = p_job_id
   for update;

  if not found
     or v_job.status <> 'running'
     or v_job.lease_owner is distinct from btrim(p_worker_id)
     or v_job.lease_expires_at is null
     or v_job.lease_expires_at <= now() then
    return false;
  end if;

  v_budget_text := v_job.pricing_snapshot ->> 'maximum_provider_cost_usd';
  if v_budget_text is null
     or v_budget_text !~ '^(0|[1-9][0-9]{0,9})([.][0-9]{1,10})?$' then
    return false;
  end if;
  v_job_cap := v_budget_text::numeric(20,10);
  if v_job_cap <= 0 then
    return false;
  end if;

  -- Historical unknown evidence without a matching durable reservation is
  -- unquantified exposure. Do not let any new billable operation pass it.
  -- Unknown events with a reservation are counted in outstanding exposure.
  -- An orphan unknown event has no defensible USD ceiling, so it blocks all
  -- admissions until a privileged operator repairs the evidence.
  if exists (
    select 1
      from public.generation_provider_cost_events e
      left join public.generation_provider_cost_reservations r on r.job_id = e.job_id
     where e.cost_source = 'unknown' and r.job_id is null
  ) then
    return false;
  end if;

  select coalesce(sum(e.cost_usd), 0)
    into v_daily_spent
    from public.generation_provider_cost_events e
   where e.created_at >= (date_trunc('day', now() at time zone 'UTC') at time zone 'UTC')
     and e.cost_source in ('reported', 'estimated');

  select coalesce(sum(r.reserved_cost_usd), 0)
    into v_outstanding
    from public.generation_provider_cost_reservations r
   where r.status in ('reserved', 'unknown');

  select * into v_existing
    from public.generation_provider_cost_reservations
   where job_id = p_job_id
   for update;

  if found then
    -- Reclaims/resubmissions reuse the same single reservation; never reserve twice.
    if v_existing.user_id <> v_job.user_id
       or v_existing.provider <> v_job.provider
       or v_existing.model <> v_job.model
       or v_existing.operation_key <> p_job_id::text
       or v_existing.reserved_cost_usd <> v_job_cap
       or v_existing.status not in ('reserved', 'unknown') then
      return false;
    end if;
    return v_daily_spent + v_outstanding <= v_policy.daily_budget_usd
       and v_outstanding <= v_policy.max_outstanding_reserved_usd;
  end if;

  if v_daily_spent + v_outstanding + v_job_cap > v_policy.daily_budget_usd
     or v_outstanding + v_job_cap > v_policy.max_outstanding_reserved_usd then
    return false;
  end if;

  insert into public.generation_provider_cost_reservations(
    job_id, user_id, provider, model, operation_key, reserved_cost_usd, status
  ) values (
    p_job_id, v_job.user_id, v_job.provider, v_job.model,
    p_job_id::text, v_job_cap, 'reserved'
  );

  return true;
end;
$$;

revoke all on function public.authorize_generation_provider_operation(uuid, text)
  from public, anon, authenticated;
grant execute on function public.authorize_generation_provider_operation(uuid, text)
  to service_role;

-- Explicit operator reconciliation. Never infer "no charge" from a timeout,
-- expired worker lease, missing usage object, or generic provider exception.
create or replace function public.resolve_generation_provider_reservation(
  p_job_id uuid,
  p_resolution_key text,
  p_resolution text,
  p_actual_cost_usd numeric,
  p_note text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_reservation public.generation_provider_cost_reservations%rowtype;
  v_operation_key text;
begin
  if p_job_id is null
     or p_resolution_key is null or length(p_resolution_key) not between 8 and 160
     or p_resolution is null
     or p_resolution not in ('release_no_charge', 'settle_known_cost')
     or p_note is null or length(btrim(p_note)) not between 8 and 1000
     or (p_resolution = 'release_no_charge' and p_actual_cost_usd is not null)
     or (p_resolution = 'settle_known_cost' and
         (p_actual_cost_usd is null or p_actual_cost_usd < 0 or p_actual_cost_usd > 1000000000)) then
    raise exception 'Provider reservation reconciliation input is invalid'
      using errcode = '22023';
  end if;

  perform 1 from public.provider_budget_policy where singleton = true for update;
  select * into v_job from public.generation_jobs where id = p_job_id for update;
  if not found then
    return false;
  end if;
  select * into v_reservation
    from public.generation_provider_cost_reservations
   where job_id = p_job_id
   for update;

  if not found then
    return false;
  end if;

  if p_resolution = 'release_no_charge' then
    if v_reservation.status not in ('reserved', 'unknown') then
      return false;
    end if;
    update public.generation_provider_cost_reservations
       set status = 'released', released_at = now(), settled_at = null,
           updated_at = now(), resolution = 'operator_confirmed_no_charge',
           resolution_note = btrim(p_note), resolved_by = session_user
     where job_id = p_job_id;
    return true;
  end if;

  v_operation_key := 'provider-reconciliation:' || p_resolution_key;
  -- The append-only cost ledger remains the source of truth. Its trigger settles
  -- the reservation. Duplicate resolution keys are checked by the ledger's
  -- existing (job_id, operation_key) unique constraint.
  perform public.record_generation_provider_cost(
    p_job_id, v_job.user_id, v_operation_key, v_job.provider, v_job.model,
    null, p_actual_cost_usd, 'estimated', null, null, null, 'unknown',
    jsonb_build_object('source', 'operator_reconciliation', 'note', btrim(p_note))
  );
  return true;
end;
$$;

revoke all on function public.resolve_generation_provider_reservation(uuid, text, text, numeric, text)
  from public, anon, authenticated;
grant execute on function public.resolve_generation_provider_reservation(uuid, text, text, numeric, text)
  to service_role;

comment on table public.provider_budget_policy is
  'Operator-configured global provider spend limits. No defaults are seeded; disabled policy blocks billable calls.';
comment on table public.generation_provider_cost_reservations is
  'Durable per-job maximum USD exposure reservations; worker lease expiry never releases a reservation.';

