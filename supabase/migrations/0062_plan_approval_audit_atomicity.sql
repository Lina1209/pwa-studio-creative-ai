-- Add the central admin audit journal write to the plan approval transaction.
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

  perform public.record_admin_audit_event(
    p_actor_user_id,
    'admin.tariff.change.approved',
    'approved',
    'tariff',
    v_id,
    null,
    p_approval_reason
  );

  return query select v_id, v_draft.plan_code, v_draft.plan_version, false;
end;
$$;

revoke all on function public.approve_plan_catalog_draft(uuid,uuid,text)
  from public, anon, authenticated;
grant execute on function public.approve_plan_catalog_draft(uuid,uuid,text) to service_role;
