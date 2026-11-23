-- Private, append-only registry foundation for delegated finance authorization.
-- No application role can read or mutate these tables directly. A later reviewed
-- backend/RPC layer must resolve grants and perform assignments with dual control.

create table if not exists public.finance_role_assignments (
  id uuid primary key default gen_random_uuid(),
  principal_id uuid not null references auth.users(id) on delete restrict,
  role_code text not null check (role_code in (
    'finance_operator', 'finance_approver', 'finance_executor',
    'support_readonly', 'auditor_readonly'
  )),
  scope_key text,
  valid_from timestamptz not null default now(),
  valid_until timestamptz,
  granted_by uuid not null references auth.users(id) on delete restrict,
  reason text not null check (length(reason) between 1 and 500),
  created_at timestamptz not null default now(),
  constraint finance_role_assignment_validity check (
    valid_until is null or valid_until > valid_from
  )
);

create index if not exists finance_role_assignments_principal_idx
  on public.finance_role_assignments (principal_id, valid_from desc, id desc);
create index if not exists finance_role_assignments_expiry_idx
  on public.finance_role_assignments (valid_until)
  where valid_until is not null;

-- Revocation is a separate append-only fact; the original grant is never edited.
create table if not exists public.finance_role_revocations (
  id uuid primary key default gen_random_uuid(),
  assignment_id uuid not null unique
    references public.finance_role_assignments(id) on delete restrict,
  revoked_by uuid not null references auth.users(id) on delete restrict,
  reason text not null check (length(reason) between 1 and 500),
  revoked_at timestamptz not null default now()
);

create index if not exists finance_role_revocations_actor_idx
  on public.finance_role_revocations (revoked_by, revoked_at desc);

-- Security event stream records grant/revoke outcomes. It intentionally stores
-- UUIDs and policy metadata only, never email addresses, credentials, or tokens.
create table if not exists public.finance_authorization_events (
  id uuid primary key default gen_random_uuid(),
  occurred_at timestamptz not null default now(),
  assignment_id uuid references public.finance_role_assignments(id) on delete restrict,
  actor_user_id uuid not null references auth.users(id) on delete restrict,
  target_principal_id uuid not null references auth.users(id) on delete restrict,
  event_type text not null check (event_type in (
    'role.granted', 'role.revoked', 'role.grant.denied', 'role.revoke.denied'
  )),
  role_code text not null check (role_code in (
    'finance_operator', 'finance_approver', 'finance_executor',
    'support_readonly', 'auditor_readonly'
  )),
  scope_key text,
  reason text not null check (length(reason) between 1 and 500)
);

create index if not exists finance_authorization_events_timeline_idx
  on public.finance_authorization_events (occurred_at desc, id desc);
create index if not exists finance_authorization_events_target_idx
  on public.finance_authorization_events (target_principal_id, occurred_at desc);

create or replace function public.prevent_finance_authorization_history_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  raise exception 'finance authorization history is append-only'
    using errcode = '55000';
end;
$$;

drop trigger if exists finance_role_assignments_no_mutation on public.finance_role_assignments;
create trigger finance_role_assignments_no_mutation
  before update or delete on public.finance_role_assignments
  for each row execute function public.prevent_finance_authorization_history_mutation();

drop trigger if exists finance_role_revocations_no_mutation on public.finance_role_revocations;
create trigger finance_role_revocations_no_mutation
  before update or delete on public.finance_role_revocations
  for each row execute function public.prevent_finance_authorization_history_mutation();

drop trigger if exists finance_authorization_events_no_mutation on public.finance_authorization_events;
create trigger finance_authorization_events_no_mutation
  before update or delete on public.finance_authorization_events
  for each row execute function public.prevent_finance_authorization_history_mutation();

alter table public.finance_role_assignments enable row level security;
alter table public.finance_role_revocations enable row level security;
alter table public.finance_authorization_events enable row level security;

revoke all on public.finance_role_assignments from public, anon, authenticated, service_role;
revoke all on public.finance_role_revocations from public, anon, authenticated, service_role;
revoke all on public.finance_authorization_events from public, anon, authenticated, service_role;
revoke all on function public.prevent_finance_authorization_history_mutation()
  from public, anon, authenticated, service_role;
