-- Add explicit audit actions for finance request lifecycle and catalog draft creation.
alter table public.admin_audit_events drop constraint if exists admin_audit_events_resource_type_check;
alter table public.admin_audit_events add constraint admin_audit_events_resource_type_check check (resource_type in (
 'platform','user','support_ticket','tariff','payment','credit_wallet','credit_ledger',
 'pricing_catalog_draft','plan_catalog_draft','finance_request','permission','security_setting'
));
alter table public.admin_audit_events drop constraint if exists admin_audit_events_action_check;
alter table public.admin_audit_events add constraint admin_audit_events_action_check check (action in (
 'admin.access','admin.permission.denied','admin.user.view','admin.support.view',
 'admin.support.reply','admin.support.status.changed','admin.tariff.change.requested',
 'admin.tariff.change.approved','admin.finance.operation.requested',
 'admin.finance.operation.approved','admin.finance.operation.executed',
 'admin.finance.role.grant','admin.finance.role.revoke',
 'admin.finance.request.create','admin.finance.request.decide','admin.finance.request.cancel',
 'admin.pricing.draft.create','admin.plan.draft.create','admin.security.settings.changed'
));
create or replace function public.record_admin_audit_event(
 p_actor_user_id uuid,p_action text,p_outcome text,p_resource_type text,
 p_resource_id uuid default null,p_correlation_id uuid default null,p_reason text default null
) returns uuid language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_id uuid;
begin
 if p_actor_user_id is null
 or p_action not in (
  'admin.access','admin.permission.denied','admin.user.view','admin.support.view',
  'admin.support.reply','admin.support.status.changed','admin.tariff.change.requested',
  'admin.tariff.change.approved','admin.finance.operation.requested',
  'admin.finance.operation.approved','admin.finance.operation.executed',
  'admin.finance.role.grant','admin.finance.role.revoke',
  'admin.finance.request.create','admin.finance.request.decide','admin.finance.request.cancel',
  'admin.pricing.draft.create','admin.plan.draft.create','admin.security.settings.changed'
 )
 or p_outcome not in ('allowed','denied','requested','approved','executed','failed')
 or p_resource_type not in (
  'platform','user','support_ticket','tariff','payment','credit_wallet','credit_ledger',
  'pricing_catalog_draft','plan_catalog_draft','finance_request','permission','security_setting'
 )
 or (p_reason is not null and length(p_reason)>500) then
  raise exception 'invalid admin audit event' using errcode='22023';
 end if;
 insert into public.admin_audit_events(actor_user_id,action,outcome,resource_type,resource_id,correlation_id,reason)
 values(p_actor_user_id,p_action,p_outcome,p_resource_type,p_resource_id,p_correlation_id,p_reason)
 returning id into v_id;
 return v_id;
end; $$;
revoke all on function public.record_admin_audit_event(uuid,text,text,text,uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.record_admin_audit_event(uuid,text,text,text,uuid,uuid,text) to service_role;
