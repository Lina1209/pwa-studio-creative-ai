-- Harden pending assignment event keys and persist assignment request audit atomically.
create or replace function public.create_pending_user_plan_assignment(
  p_user_id uuid,
  p_approved_plan_version_id uuid,
  p_assignment_source text,
  p_source_reference text,
  p_idempotency_key text,
  p_starts_at timestamptz,
  p_ends_at timestamptz,
  p_actor_user_id uuid,
  p_reason text
)
returns table(assignment_id uuid, status text, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing public.user_plan_assignments%rowtype;
  v_assignment_id uuid;
begin
  if p_user_id is null or p_approved_plan_version_id is null
     or p_actor_user_id is null
     or p_assignment_source is null
     or p_assignment_source not in ('operator_grant','free_grant','verified_payment','migration')
     or p_source_reference is null or char_length(p_source_reference) not between 8 and 240
     or p_idempotency_key is null or char_length(p_idempotency_key) not between 8 and 200
     or p_starts_at is null or p_ends_at is null or p_ends_at <= p_starts_at
     or p_reason is null or char_length(p_reason) not between 8 and 500 then
    raise exception 'invalid plan assignment parameters' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended('user-plan-assignment:' || p_user_id::text || ':' || p_idempotency_key, 0)
  );

  if not exists (select 1 from auth.users where id = p_user_id) then
    raise exception 'target user not found' using errcode = 'P0002';
  end if;
  if not exists (select 1 from auth.users where id = p_actor_user_id) then
    raise exception 'verified actor user not found' using errcode = 'P0002';
  end if;
  if not exists (
    select 1 from public.approved_plan_versions where id = p_approved_plan_version_id
  ) then
    raise exception 'approved plan version not found' using errcode = 'P0002';
  end if;

  select * into v_existing from public.user_plan_assignments
   where user_id = p_user_id and idempotency_key = p_idempotency_key;
  if found then
    if v_existing.approved_plan_version_id is distinct from p_approved_plan_version_id
       or v_existing.assignment_source is distinct from p_assignment_source
       or v_existing.source_reference is distinct from p_source_reference
       or v_existing.starts_at is distinct from p_starts_at
       or v_existing.ends_at is distinct from p_ends_at
       or v_existing.created_by is distinct from p_actor_user_id
       or v_existing.metadata->>'reason' is distinct from p_reason then
      raise exception 'assignment idempotency key reused with different parameters'
        using errcode = '23505';
    end if;
    return query select v_existing.id, v_existing.status, true;
    return;
  end if;

  insert into public.user_plan_assignments(
    user_id, approved_plan_version_id, assignment_source, source_reference,
    idempotency_key, status, starts_at, ends_at, created_by, metadata
  ) values (
    p_user_id, p_approved_plan_version_id, p_assignment_source, p_source_reference,
    p_idempotency_key, 'pending', p_starts_at, p_ends_at, p_actor_user_id,
    jsonb_build_object('reason', p_reason)
  ) returning id into v_assignment_id;

  insert into public.user_plan_assignment_events(
    assignment_id, user_id, event_type, actor_user_id, event_key, reason
  ) values (
    v_assignment_id, p_user_id, 'created', p_actor_user_id,
    'created:' || md5(p_idempotency_key), p_reason
  );

  perform public.record_admin_audit_event(
    p_actor_user_id,
    'admin.tariff.change.requested',
    'requested',
    'tariff',
    v_assignment_id,
    null,
    p_reason
  );

  return query select v_assignment_id, 'pending'::text, false;
end;
$$;

revoke all on function public.create_pending_user_plan_assignment(uuid,uuid,text,text,text,timestamptz,timestamptz,uuid,text)
  from public, anon, authenticated;
grant execute on function public.create_pending_user_plan_assignment(uuid,uuid,text,text,text,timestamptz,timestamptz,uuid,text)
  to service_role;
