-- Serialize grants for the same principal/role/scope and reject duplicate active assignments.
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
  v_lock_key bigint;
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

  v_lock_key := hashtextextended(
    p_principal_id::text || ':' || p_role_code || ':' || coalesce(p_scope_key, '<global>'),
    0
  );
  perform pg_advisory_xact_lock(v_lock_key);

  if exists (
    select 1
      from public.finance_role_assignments a
     where a.principal_id = p_principal_id
       and a.role_code = p_role_code
       and a.scope_key is not distinct from p_scope_key
       and a.valid_from <= now()
       and (a.valid_until is null or a.valid_until > now())
       and not exists (
         select 1 from public.finance_role_revocations r
          where r.assignment_id = a.id
       )
  ) then
    raise exception 'an active finance role assignment already exists'
      using errcode = '23505';
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
