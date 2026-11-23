-- Restrict quota state mutations to the SECURITY DEFINER RPC boundary.
revoke all on public.plan_quota_reservations
  from public, anon, authenticated, service_role;
revoke all on public.plan_quota_events
  from public, anon, authenticated, service_role;

revoke all on function public.prevent_plan_quota_event_mutation()
  from public, anon, authenticated, service_role;

grant execute on function public.reserve_plan_quota(uuid,uuid,text,text,integer)
  to service_role;
grant execute on function public.finish_plan_quota_reservation(uuid,uuid,text)
  to service_role;

comment on table public.plan_quota_reservations is
  'Private mutable reservation projection. All writes occur only inside service-role-only transactional RPCs; direct REST table access is revoked.';
comment on table public.plan_quota_events is
  'Private append-only quota lifecycle journal. Events are inserted only by transactional SECURITY DEFINER RPCs.';
