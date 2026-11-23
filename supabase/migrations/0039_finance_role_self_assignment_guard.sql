-- Enforce separation of duties at the database RPC boundary as well as the API.
create or replace function public.grant_finance_role(
  p_principal_id uuid,
  p_role_code text,
  p_scope_key text,
  p_valid_until timestamptz,
  p_granted_by uuid,
  p_reason text
)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_assignment_id uuid;
begin
  if p_principal_id is null or p_granted_by is null
     or p_principal_id = p_granted_by
     or p_role_code not in (
       'finance_operator', 'finance_approver', 'finance_executor',
       'support_readonly', 'auditor_readonly'
     )
     or (p_scope_key is not null and length(p_scope_key) not between 1 and 200)
     or (p_valid_until is not null and p_valid_until <= now())
     or p_reason is null or length(p_reason) not between 1 and 500 then
    raise exception 'invalid finance role assignment' using errcode = '22023';
  end if;

  insert into public.finance_role_assignments(
    principal_id, role_code, scope_key, valid_from, valid_until, granted_by, reason
  ) values (
    p_principal_id, p_role_code, p_scope_key, now(), p_valid_until, p_granted_by, p_reason
  ) returning id into v_assignment_id;

  insert into public.finance_authorization_events(
    assignment_id, actor_user_id, target_principal_id,
    event_type, role_code, scope_key, reason
  ) values (
    v_assignment_id, p_granted_by, p_principal_id,
    'role.granted', p_role_code, p_scope_key, p_reason
  );

  return v_assignment_id;
end;
$$;

revoke all on function public.grant_finance_role(uuid,text,text,timestamptz,uuid,text)
  from public, anon, authenticated;
grant execute on function public.grant_finance_role(uuid,text,text,timestamptz,uuid,text)
  to service_role;
