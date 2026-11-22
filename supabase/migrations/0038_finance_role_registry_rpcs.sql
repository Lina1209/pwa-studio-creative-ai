-- Narrow server-only RPCs for finance role registry access.
-- The API must independently authorize the verified actor before invoking
-- grant/revoke. These functions are not callable by browser roles.

create or replace function public.read_active_finance_role_assignments(
  p_principal_id uuid
)
returns table (
  assignment_id uuid,
  principal_id uuid,
  role_code text,
  scope_key text,
  valid_from timestamptz,
  valid_until timestamptz,
  granted_by uuid,
  created_at timestamptz
)
language plpgsql
stable
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_principal_id is null then
    raise exception 'principal id is required' using errcode = '22023';
  end if;

  return query
    select a.id, a.principal_id, a.role_code, a.scope_key,
           a.valid_from, a.valid_until, a.granted_by, a.created_at
      from public.finance_role_assignments a
     where a.principal_id = p_principal_id
       and a.valid_from <= now()
       and (a.valid_until is null or a.valid_until > now())
       and not exists (
         select 1 from public.finance_role_revocations r
          where r.assignment_id = a.id
       )
     order by a.created_at desc, a.id desc;
end;
$$;

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

create or replace function public.revoke_finance_role(
  p_assignment_id uuid,
  p_revoked_by uuid,
  p_reason text
)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_assignment public.finance_role_assignments%rowtype;
  v_revocation_id uuid;
begin
  if p_assignment_id is null or p_revoked_by is null
     or p_reason is null or length(p_reason) not between 1 and 500 then
    raise exception 'invalid finance role revocation' using errcode = '22023';
  end if;

  select * into v_assignment
    from public.finance_role_assignments
   where id = p_assignment_id
   for update;
  if not found then
    raise exception 'finance role assignment not found' using errcode = 'P0002';
  end if;

  insert into public.finance_role_revocations(
    assignment_id, revoked_by, reason
  ) values (
    p_assignment_id, p_revoked_by, p_reason
  ) returning id into v_revocation_id;

  insert into public.finance_authorization_events(
    assignment_id, actor_user_id, target_principal_id,
    event_type, role_code, scope_key, reason
  ) values (
    v_assignment.id, p_revoked_by, v_assignment.principal_id,
    'role.revoked', v_assignment.role_code, v_assignment.scope_key, p_reason
  );

  return v_revocation_id;
end;
$$;

revoke all on function public.read_active_finance_role_assignments(uuid)
  from public, anon, authenticated;
revoke all on function public.grant_finance_role(uuid,text,text,timestamptz,uuid,text)
  from public, anon, authenticated;
revoke all on function public.revoke_finance_role(uuid,uuid,text)
  from public, anon, authenticated;
grant execute on function public.read_active_finance_role_assignments(uuid) to service_role;
grant execute on function public.grant_finance_role(uuid,text,text,timestamptz,uuid,text) to service_role;
grant execute on function public.revoke_finance_role(uuid,uuid,text) to service_role;
