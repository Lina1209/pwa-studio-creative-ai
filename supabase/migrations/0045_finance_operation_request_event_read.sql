-- Read-only event timeline for a finance request; service-role only.
create or replace function public.read_finance_operation_request_events(p_request_id uuid)
returns table (
  event_id uuid,
  actor_id uuid,
  event_type text,
  previous_status text,
  new_status text,
  reason text,
  occurred_at timestamptz
)
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
  select e.id, e.actor_id, e.event_type, e.previous_status,
         e.new_status, e.reason, e.occurred_at
    from public.finance_operation_request_events e
   where e.request_id = p_request_id
   order by e.occurred_at asc, e.id asc
   limit 100
$$;

revoke all on function public.read_finance_operation_request_events(uuid)
  from public, anon, authenticated;
grant execute on function public.read_finance_operation_request_events(uuid)
  to service_role;
