-- PWA Studio: owner-only aggregate registration and activity analytics.
-- Source-only until the live migration ledger, table definitions, grants and RLS
-- are reconciled. This migration must not be applied blindly to production.

create or replace function public.admin_analytics_summary(
  p_start_at timestamptz,
  p_end_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_registered bigint;
  v_project_accounts bigint;
  v_ai_accounts bigint;
begin
  if p_start_at is null or p_end_at is null
     or p_start_at >= p_end_at
     or p_end_at > now() + interval '5 minutes'
     or p_end_at - p_start_at > interval '31 days' then
    raise exception 'Invalid analytics date range';
  end if;

  select count(*) into v_registered
    from public.profiles
    where created_at >= p_start_at and created_at < p_end_at;

  select count(distinct owner_id) into v_project_accounts
    from public.projects
    where updated_at >= p_start_at and updated_at < p_end_at
      and project_type = 'movie';

  select count(distinct user_id) into v_ai_accounts
    from public.ai_usage
    where created_at >= p_start_at and created_at < p_end_at;

  return jsonb_build_object(
    'registered_accounts', v_registered,
    'accounts_with_project_updates', v_project_accounts,
    'accounts_with_successful_ai_usage', v_ai_accounts
  );
end;
$$;

revoke all on function public.admin_analytics_summary(timestamptz, timestamptz)
  from public, anon, authenticated;
grant execute on function public.admin_analytics_summary(timestamptz, timestamptz)
  to service_role;
