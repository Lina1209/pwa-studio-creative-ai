-- PWA Studio: append-only provider cost and usage evidence for durable generation jobs.
-- This is an internal cost-audit trail, not a user credit ledger or a payment system.
-- No pricing assumptions or automatic customer debits are introduced.

do $$
begin
  if to_regclass('public.generation_jobs') is null then
    raise exception 'Migration 0022 requires public.generation_jobs and migrations 0009+.';
  end if;
  if not exists (
    select 1 from pg_constraint
     where conrelid = 'public.generation_jobs'::regclass
       and conname = 'generation_jobs_id_user_id_key'
  ) then
    raise exception 'Migration 0022 requires the generation job owner composite key from migration 0018.';
  end if;
end;
$$;

create table if not exists public.generation_provider_cost_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete restrict,
  job_id uuid not null,
  operation_key text not null check (length(operation_key) between 8 and 200),
  provider text not null check (length(provider) between 1 and 100),
  model text not null check (length(model) between 1 and 200),
  provider_usage_id text,
  cost_usd numeric(20,10),
  cost_source text not null check (cost_source in ('reported', 'estimated', 'unknown')),
  input_units bigint check (input_units is null or input_units >= 0),
  output_units bigint check (output_units is null or output_units >= 0),
  total_units bigint check (total_units is null or total_units >= 0),
  unit_kind text not null default 'unknown'
    check (unit_kind in ('token', 'image', 'second', 'character', 'request', 'unknown')),
  metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(metadata) = 'object' and octet_length(metadata::text) <= 16384),
  budget_limit_usd numeric(20,10),
  cumulative_known_cost_usd numeric(20,10) not null default 0
    check (cumulative_known_cost_usd >= 0),
  budget_exceeded boolean,
  created_at timestamptz not null default now(),
  constraint generation_provider_cost_events_cost_source_check check (
    (cost_source = 'unknown' and cost_usd is null)
    or (cost_source in ('reported', 'estimated') and cost_usd is not null and cost_usd >= 0)
  ),
  constraint generation_provider_cost_events_budget_check check (
    budget_limit_usd is null or budget_limit_usd >= 0
  ),
  constraint generation_provider_cost_events_job_owner_fkey
    foreign key (job_id, user_id)
    references public.generation_jobs(id, user_id) on delete restrict,
  constraint generation_provider_cost_events_job_operation_key_key
    unique (job_id, operation_key)
);

create unique index if not exists generation_provider_cost_events_provider_usage_uidx
  on public.generation_provider_cost_events(provider, provider_usage_id)
  where provider_usage_id is not null;
create index if not exists generation_provider_cost_events_user_created_idx
  on public.generation_provider_cost_events(user_id, created_at desc);
create index if not exists generation_provider_cost_events_job_created_idx
  on public.generation_provider_cost_events(job_id, created_at);

alter table public.generation_provider_cost_events enable row level security;
revoke all on public.generation_provider_cost_events from anon, authenticated;
grant select, insert on public.generation_provider_cost_events to service_role;
revoke update, delete, truncate on public.generation_provider_cost_events from service_role;
grant usage, select on sequence public.generation_provider_cost_events_id_seq to service_role;

create or replace function public.reject_generation_provider_cost_event_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  raise exception 'Provider cost events are append-only; write a compensating audit event.'
    using errcode = '55000';
end;
$$;

drop trigger if exists generation_provider_cost_events_append_only
  on public.generation_provider_cost_events;
create trigger generation_provider_cost_events_append_only
before update or delete on public.generation_provider_cost_events
for each row execute function public.reject_generation_provider_cost_event_mutation();

create or replace function public.record_generation_provider_cost(
  p_job_id uuid,
  p_user_id uuid,
  p_operation_key text,
  p_provider text,
  p_model text,
  p_provider_usage_id text,
  p_cost_usd numeric,
  p_cost_source text,
  p_input_units bigint,
  p_output_units bigint,
  p_total_units bigint,
  p_unit_kind text,
  p_metadata jsonb
)
returns table(
  event_id bigint,
  created boolean,
  cumulative_known_cost_usd numeric,
  budget_limit_usd numeric,
  budget_exceeded boolean
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_existing public.generation_provider_cost_events%rowtype;
  v_event public.generation_provider_cost_events%rowtype;
  v_inserted integer := 0;
  v_budget_text text;
  v_budget numeric(20,10);
  v_known_total numeric(20,10);
  v_has_unknown boolean;
  v_exceeded boolean;
begin
  if p_job_id is null or p_user_id is null
     or p_operation_key is null or length(p_operation_key) not between 8 and 200
     or p_provider is null or length(p_provider) not between 1 and 100
     or p_model is null or length(p_model) not between 1 and 200
     or (p_provider_usage_id is not null and length(p_provider_usage_id) not between 1 and 255)
     or p_cost_source is null
     or p_cost_source not in ('reported', 'estimated', 'unknown')
     or (p_cost_source = 'unknown' and p_cost_usd is not null)
     or (p_cost_source in ('reported', 'estimated')
         and (p_cost_usd is null or p_cost_usd < 0 or p_cost_usd > 1000000000))
     or p_input_units < 0 or p_output_units < 0 or p_total_units < 0
     or p_unit_kind is null
     or p_unit_kind not in ('token', 'image', 'second', 'character', 'request', 'unknown')
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 16384 then
    raise exception 'Provider cost event input is invalid' using errcode = '22023';
  end if;

  select * into v_job
    from public.generation_jobs as job
   where job.id = p_job_id and job.user_id = p_user_id
   for update;
  if not found then
    raise exception 'Generation job owner does not match' using errcode = '42501';
  end if;
  if p_provider <> v_job.provider or p_model <> v_job.model then
    raise exception 'Provider cost event does not match the immutable job provider/model'
      using errcode = '22023';
  end if;

  select * into v_existing
    from public.generation_provider_cost_events as event
   where event.job_id = p_job_id and event.operation_key = p_operation_key;
  if found then
    if v_existing.user_id <> p_user_id
       or v_existing.provider <> p_provider
       or v_existing.model <> p_model
       or v_existing.provider_usage_id is distinct from p_provider_usage_id
       or v_existing.cost_usd is distinct from p_cost_usd
       or v_existing.cost_source <> p_cost_source
       or v_existing.input_units is distinct from p_input_units
       or v_existing.output_units is distinct from p_output_units
       or v_existing.total_units is distinct from p_total_units
       or v_existing.unit_kind <> p_unit_kind
       or v_existing.metadata <> p_metadata then
      raise exception 'Provider cost idempotency key was reused with different evidence'
        using errcode = '22023';
    end if;
    return query select v_existing.id, false,
      v_existing.cumulative_known_cost_usd,
      v_existing.budget_limit_usd, v_existing.budget_exceeded;
    return;
  end if;

  v_budget_text := v_job.pricing_snapshot ->> 'maximum_provider_cost_usd';
  if v_budget_text is not null then
    if v_budget_text !~ '^(0|[1-9][0-9]{0,9})([.][0-9]{1,10})?$' then
      raise exception 'Generation job provider cost budget snapshot is invalid'
        using errcode = '22023';
    end if;
    v_budget := v_budget_text::numeric(20,10);
  end if;

  select coalesce(sum(event.cost_usd), 0),
         coalesce(bool_or(event.cost_source = 'unknown'), false)
    into v_known_total, v_has_unknown
    from public.generation_provider_cost_events as event
   where event.job_id = p_job_id;

  if p_cost_usd is not null then
    v_known_total := v_known_total + p_cost_usd;
  else
    v_has_unknown := true;
  end if;

  if v_budget is null then
    v_exceeded := null;
  elsif v_known_total > v_budget then
    v_exceeded := true;
  elsif v_has_unknown then
    v_exceeded := null;
  else
    v_exceeded := false;
  end if;

  insert into public.generation_provider_cost_events(
    user_id, job_id, operation_key, provider, model, provider_usage_id,
    cost_usd, cost_source, input_units, output_units, total_units, unit_kind,
    metadata, budget_limit_usd, cumulative_known_cost_usd, budget_exceeded
  ) values (
    p_user_id, p_job_id, p_operation_key, p_provider, p_model, p_provider_usage_id,
    p_cost_usd, p_cost_source, p_input_units, p_output_units, p_total_units, p_unit_kind,
    p_metadata, v_budget, v_known_total, v_exceeded
  )
  returning * into v_event;
  get diagnostics v_inserted = row_count;

  return query select v_event.id, v_inserted = 1,
    v_event.cumulative_known_cost_usd,
    v_event.budget_limit_usd, v_event.budget_exceeded;
end;
$$;

revoke all on function public.record_generation_provider_cost(
  uuid, uuid, text, text, text, text, numeric, text, bigint, bigint, bigint, text, jsonb
) from public, anon, authenticated;
grant execute on function public.record_generation_provider_cost(
  uuid, uuid, text, text, text, text, numeric, text, bigint, bigint, bigint, text, jsonb
) to service_role;
