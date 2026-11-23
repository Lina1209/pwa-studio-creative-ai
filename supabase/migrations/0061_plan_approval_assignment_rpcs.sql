-- PWA Studio: controlled, service-role-only plan approval and pending assignment.
-- No activation, checkout, payment handling, credit grants or production deployment.

create or replace function public.approve_plan_catalog_draft(
  p_draft_id uuid,
  p_actor_user_id uuid,
  p_approval_reason text
)
returns table(approved_plan_version_id uuid, plan_code text, plan_version integer, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_draft public.plan_catalog_drafts%rowtype;
  v_existing public.approved_plan_versions%rowtype;
  v_id uuid;
begin
  if p_draft_id is null or p_actor_user_id is null
     or p_approval_reason is null
     or char_length(p_approval_reason) not between 8 and 500 then
    raise exception 'invalid plan approval parameters' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(hashtextextended('plan-draft:' || p_draft_id::text, 0));

  select * into v_draft from public.plan_catalog_drafts where id = p_draft_id;
  if not found then
    raise exception 'plan draft not found' using errcode = 'P0002';
  end if;

  select * into v_existing from public.approved_plan_versions
   where source_draft_id = p_draft_id;
  if found then
    if v_existing.approved_by is distinct from p_actor_user_id
       or v_existing.approval_reason is distinct from p_approval_reason then
      raise exception 'draft was already approved with different approval details'
        using errcode = '23505';
    end if;
    return query select v_existing.id, v_existing.plan_code, v_existing.plan_version, true;
    return;
  end if;

  insert into public.approved_plan_versions(
    source_draft_id, plan_code, plan_version, display_name, billing_period,
    period_days, credits_per_period, price_minor, currency, limits_json,
    features_json, approved_by, approval_reason
  ) values (
    v_draft.id, v_draft.plan_code, v_draft.plan_version, v_draft.display_name,
    v_draft.billing_period, v_draft.period_days, v_draft.credits_per_period,
    v_draft.price_minor, v_draft.currency, v_draft.limits_json,
    v_draft.features_json, p_actor_user_id, p_approval_reason
  ) returning id into v_id;

  return query select v_id, v_draft.plan_code, v_draft.plan_version, false;
end;
$$;

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
       or v_existing.created_by is distinct from p_actor_user_id then
      raise exception 'assignment idempotency key reused with different parameters'
        using errcode = '23505';
    end if;
    return query select v_existing.id, v_existing.status, true;
    return;
  end if;

  -- Pending assignments are inert and do not count as active entitlements.
  -- Activation requires a separately reviewed lifecycle operation.
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
    'created:' || p_idempotency_key, p_reason
  );

  return query select v_assignment_id, 'pending'::text, false;
end;
$$;

revoke all on function public.approve_plan_catalog_draft(uuid,uuid,text)
  from public, anon, authenticated;
revoke all on function public.create_pending_user_plan_assignment(uuid,uuid,text,text,text,timestamptz,timestamptz,uuid,text)
  from public, anon, authenticated;
grant execute on function public.approve_plan_catalog_draft(uuid,uuid,text) to service_role;
grant execute on function public.create_pending_user_plan_assignment(uuid,uuid,text,text,text,timestamptz,timestamptz,uuid,text)
  to service_role;

comment on function public.approve_plan_catalog_draft(uuid,uuid,text) is
  'Service-role only. Backend must verify admin permission before calling. Copies one immutable draft to an approved snapshot; does not activate it.';
comment on function public.create_pending_user_plan_assignment(uuid,uuid,text,text,text,timestamptz,timestamptz,uuid,text) is
  'Service-role only. Backend must verify admin permission and source evidence. Creates an inert pending assignment only; no activation or credit grant.';
