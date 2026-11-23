-- Trusted backend bridge for owner-scoped cancellation.
-- The API must pass the immutable user UUID from its verified Supabase JWT;
-- this service-role-only wrapper never accepts identity from a browser payload.
create or replace function public.request_generation_job_cancellation_for_owner(
  p_job_id uuid,
  p_user_id uuid
)
returns table(job_status text, cancellation_action text, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_user_id is null then
    raise exception 'Verified owner identity is required' using errcode = '28000';
  end if;
  if p_job_id is null then
    raise exception 'job_id is required' using errcode = '22023';
  end if;

  -- auth.uid() reads this transaction-local claim. This function is callable
  -- only by service_role, and the API derives p_user_id from verified JWT.sub.
  perform set_config('request.jwt.claim.sub', p_user_id::text, true);
  return query
    select * from public.request_generation_job_cancellation(p_job_id);
end;
$$;

revoke all on function public.request_generation_job_cancellation_for_owner(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.request_generation_job_cancellation_for_owner(uuid, uuid)
  to service_role;

comment on function public.request_generation_job_cancellation_for_owner(uuid, uuid) is
  'Service-role-only bridge for a trusted backend. p_user_id must come from a cryptographically verified user JWT, never a request body; delegates to the owner-scoped cancellation RPC.';
