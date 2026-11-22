-- Append-only administrative security audit journal.
-- Writes and reads are exposed only through bounded SECURITY DEFINER RPCs to service_role.
create table if not exists public.admin_audit_events (
  id uuid primary key default gen_random_uuid(),
  occurred_at timestamptz not null default now(),
  actor_user_id uuid not null,
  action text not null check (action in (
    'admin.access', 'admin.permission.denied',
    'admin.user.view', 'admin.support.view',
    'admin.tariff.change.requested', 'admin.tariff.change.approved',
    'admin.finance.operation.requested', 'admin.finance.operation.approved',
    'admin.finance.operation.executed', 'admin.security.settings.changed'
  )),
  outcome text not null check (outcome in ('allowed', 'denied', 'requested', 'approved', 'executed', 'failed')),
  resource_type text not null check (resource_type in (
    'platform', 'user', 'support_ticket', 'tariff', 'payment', 'credit_wallet',
    'permission', 'security_setting'
  )),
  resource_id uuid,
  correlation_id uuid,
  reason text check (reason is null or length(reason) <= 500)
);

create index if not exists admin_audit_events_occurred_at_idx
  on public.admin_audit_events (occurred_at desc, id desc);
create index if not exists admin_audit_events_actor_idx
  on public.admin_audit_events (actor_user_id, occurred_at desc);

alter table public.admin_audit_events enable row level security;
revoke all on public.admin_audit_events from public, anon, authenticated;
revoke all on public.admin_audit_events from service_role;

create or replace function public.prevent_admin_audit_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  raise exception 'admin audit events are append-only'
    using errcode = '55000';
end;
$$;

drop trigger if exists admin_audit_events_no_mutation on public.admin_audit_events;
create trigger admin_audit_events_no_mutation
  before update or delete on public.admin_audit_events
  for each row execute function public.prevent_admin_audit_mutation();

create or replace function public.record_admin_audit_event(
  p_actor_user_id uuid,
  p_action text,
  p_outcome text,
  p_resource_type text,
  p_resource_id uuid default null,
  p_correlation_id uuid default null,
  p_reason text default null
)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_id uuid;
begin
  if p_actor_user_id is null
     or p_action not in (
       'admin.access', 'admin.permission.denied',
       'admin.user.view', 'admin.support.view',
       'admin.tariff.change.requested', 'admin.tariff.change.approved',
       'admin.finance.operation.requested', 'admin.finance.operation.approved',
       'admin.finance.operation.executed', 'admin.security.settings.changed'
     )
     or p_outcome not in ('allowed', 'denied', 'requested', 'approved', 'executed', 'failed')
     or p_resource_type not in (
       'platform', 'user', 'support_ticket', 'tariff', 'payment', 'credit_wallet',
       'permission', 'security_setting'
     )
     or (p_reason is not null and length(p_reason) > 500) then
    raise exception 'invalid admin audit event' using errcode = '22023';
  end if;

  insert into public.admin_audit_events (
    actor_user_id, action, outcome, resource_type, resource_id, correlation_id, reason
  ) values (
    p_actor_user_id, p_action, p_outcome, p_resource_type, p_resource_id, p_correlation_id, p_reason
  ) returning id into v_id;

  return v_id;
end;
$$;

create or replace function public.read_admin_audit_events(
  p_before timestamptz default null,
  p_limit integer default 100
)
returns table (
  id uuid,
  occurred_at timestamptz,
  actor_user_id uuid,
  action text,
  outcome text,
  resource_type text,
  resource_id uuid,
  correlation_id uuid,
  reason text
)
language plpgsql
stable
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_limit is null or p_limit not between 1 and 200 then
    raise exception 'audit page limit must be between 1 and 200'
      using errcode = '22023';
  end if;

  return query
    select e.id, e.occurred_at, e.actor_user_id, e.action, e.outcome,
           e.resource_type, e.resource_id, e.correlation_id, e.reason
      from public.admin_audit_events e
     where p_before is null or e.occurred_at < p_before
     order by e.occurred_at desc, e.id desc
     limit p_limit;
end;
$$;

revoke all on function public.prevent_admin_audit_mutation() from public, anon, authenticated, service_role;
revoke all on function public.record_admin_audit_event(uuid,text,text,text,uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.read_admin_audit_events(timestamptz,integer) from public, anon, authenticated;
grant execute on function public.record_admin_audit_event(uuid,text,text,text,uuid,uuid,text) to service_role;
grant execute on function public.read_admin_audit_events(timestamptz,integer) to service_role;
