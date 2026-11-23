-- PWA Studio: inert approved-plan snapshots and immutable user assignment history.
-- This migration creates storage only. It does not approve drafts, assign plans,
-- grant credits, enable checkout, or alter production.

create table if not exists public.approved_plan_versions (
  id uuid primary key default gen_random_uuid(),
  source_draft_id uuid not null unique
    references public.plan_catalog_drafts(id) on delete restrict,
  plan_code text not null check (plan_code ~ '^[a-z][a-z0-9_]{2,40}$'),
  plan_version integer not null check (plan_version > 0),
  display_name text not null check (char_length(display_name) between 1 and 80),
  billing_period text not null check (billing_period in ('week','month')),
  period_days integer not null check (period_days in (7,30)),
  credits_per_period bigint not null check (credits_per_period > 0),
  price_minor bigint null check (price_minor is null or price_minor >= 0),
  currency char(3) null check (currency is null or currency ~ '^[A-Z]{3}$'),
  limits_json jsonb not null default '{}'::jsonb check (
    jsonb_typeof(limits_json) = 'object' and octet_length(limits_json::text) <= 8192
  ),
  features_json jsonb not null default '[]'::jsonb check (
    jsonb_typeof(features_json) = 'array' and octet_length(features_json::text) <= 8192
  ),
  approved_by uuid not null references auth.users(id) on delete restrict,
  approval_reason text not null check (char_length(approval_reason) between 8 and 500),
  approved_at timestamptz not null default now(),
  unique(plan_code, plan_version),
  check ((billing_period = 'week' and period_days = 7)
      or (billing_period = 'month' and period_days = 30)),
  check ((price_minor is null and currency is null)
      or (price_minor is not null and currency is not null))
);

create index if not exists approved_plan_versions_code_idx
  on public.approved_plan_versions(plan_code, plan_version desc);

alter table public.approved_plan_versions enable row level security;
revoke all on public.approved_plan_versions from public, anon, authenticated;
grant select, insert on public.approved_plan_versions to service_role;

create or replace function public.prevent_approved_plan_version_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'approved plan versions are immutable; approve a new version'
    using errcode = '55000';
end;
$$;

drop trigger if exists approved_plan_versions_immutable on public.approved_plan_versions;
create trigger approved_plan_versions_immutable
before update or delete on public.approved_plan_versions
for each row execute function public.prevent_approved_plan_version_mutation();

-- Assignment rows are append-only snapshots. Future lifecycle transitions must
-- append a separate event and be implemented through a reviewed transactional RPC.
create table if not exists public.user_plan_assignments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete restrict,
  approved_plan_version_id uuid not null
    references public.approved_plan_versions(id) on delete restrict,
  assignment_source text not null
    check (assignment_source in ('operator_grant','free_grant','verified_payment','migration')),
  source_reference text not null check (char_length(source_reference) between 8 and 240),
  idempotency_key text not null check (char_length(idempotency_key) between 8 and 200),
  status text not null default 'pending'
    check (status in ('pending','active','scheduled','expired','cancelled','revoked')),
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb check (
    jsonb_typeof(metadata) = 'object' and octet_length(metadata::text) <= 8192
  ),
  unique(user_id, idempotency_key),
  check (ends_at > starts_at)
);

create index if not exists user_plan_assignments_user_period_idx
  on public.user_plan_assignments(user_id, starts_at desc, ends_at desc);
create index if not exists user_plan_assignments_status_idx
  on public.user_plan_assignments(status, starts_at, ends_at);

alter table public.user_plan_assignments enable row level security;
revoke all on public.user_plan_assignments from public, anon, authenticated;
grant select, insert on public.user_plan_assignments to service_role;

create or replace function public.prevent_user_plan_assignment_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'plan assignments are immutable; append a lifecycle event'
    using errcode = '55000';
end;
$$;

drop trigger if exists user_plan_assignments_immutable on public.user_plan_assignments;
create trigger user_plan_assignments_immutable
before update or delete on public.user_plan_assignments
for each row execute function public.prevent_user_plan_assignment_mutation();

create table if not exists public.user_plan_assignment_events (
  id bigint generated always as identity primary key,
  assignment_id uuid not null
    references public.user_plan_assignments(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  event_type text not null
    check (event_type in ('created','activated','scheduled','expired','cancelled','revoked')),
  actor_user_id uuid not null references auth.users(id) on delete restrict,
  event_key text not null check (char_length(event_key) between 8 and 200),
  reason text not null check (char_length(reason) between 8 and 500),
  occurred_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb check (
    jsonb_typeof(metadata) = 'object' and octet_length(metadata::text) <= 8192
  ),
  unique(assignment_id, event_key)
);

create index if not exists user_plan_assignment_events_user_idx
  on public.user_plan_assignment_events(user_id, occurred_at desc, id desc);

alter table public.user_plan_assignment_events enable row level security;
revoke all on public.user_plan_assignment_events from public, anon, authenticated;
grant select, insert on public.user_plan_assignment_events to service_role;

create or replace function public.prevent_user_plan_assignment_event_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'plan assignment events are immutable'
    using errcode = '55000';
end;
$$;

drop trigger if exists user_plan_assignment_events_immutable on public.user_plan_assignment_events;
create trigger user_plan_assignment_events_immutable
before update or delete on public.user_plan_assignment_events
for each row execute function public.prevent_user_plan_assignment_event_mutation();

comment on table public.approved_plan_versions is
  'Immutable approved snapshots copied from drafts only by a future audited approval operation. No approval RPC is installed.';
comment on table public.user_plan_assignments is
  'Append-only user plan assignment snapshots. No assignment or activation RPC is installed by this migration.';
comment on table public.user_plan_assignment_events is
  'Append-only audit history for future plan assignment lifecycle transitions. No lifecycle transitions are enabled.';
