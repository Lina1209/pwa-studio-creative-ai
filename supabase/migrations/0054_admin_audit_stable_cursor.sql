-- Align the audit reader with the server's stable (timestamp, UUID) cursor.
-- Drop the earlier two-argument signature so PostgREST has one unambiguous RPC.
revoke all on function public.read_admin_audit_events(timestamptz, integer)
  from public, anon, authenticated, service_role;
drop function if exists public.read_admin_audit_events(timestamptz, integer);

create function public.read_admin_audit_events(
  p_before timestamptz default null,
  p_before_id uuid default null,
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

  if (p_before is null) <> (p_before_id is null) then
    raise exception 'both audit cursor fields are required'
      using errcode = '22023';
  end if;

  return query
    select e.id, e.occurred_at, e.actor_user_id, e.action, e.outcome,
           e.resource_type, e.resource_id, e.correlation_id, e.reason
      from public.admin_audit_events e
     where p_before is null
        or (e.occurred_at, e.id) < (p_before, p_before_id)
     order by e.occurred_at desc, e.id desc
     limit p_limit;
end;
$$;

revoke all on function public.read_admin_audit_events(timestamptz, uuid, integer)
  from public, anon, authenticated;
grant execute on function public.read_admin_audit_events(timestamptz, uuid, integer)
  to service_role;
