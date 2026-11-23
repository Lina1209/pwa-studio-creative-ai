\set ON_ERROR_STOP on
create extension if not exists pgcrypto;
do $roles$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end;
$roles$;

\i supabase/migrations/0035_admin_audit_journal.sql
\i supabase/migrations/0036_admin_audit_keyset_pagination.sql
\i supabase/migrations/0054_admin_audit_stable_cursor.sql
\i supabase/migrations/0080_admin_audit_resource_allowlist_alignment.sql
\i supabase/migrations/0081_admin_support_mutation_audit_actions.sql
\i supabase/migrations/0082_admin_finance_role_audit_actions.sql
\i supabase/migrations/0083_finance_and_catalog_admin_audit_actions.sql

do $admin_audit_resource_allowlist_test$
declare
  v_actor uuid := '11111111-1111-4111-8111-111111111111';
  v_resource uuid := '22222222-2222-4222-8222-222222222222';
  v_id uuid;
  v_count integer;
  v_rejected boolean;
begin
  v_id := public.record_admin_audit_event(
    v_actor, 'admin.access', 'allowed', 'credit_ledger', v_resource, null,
    'Test credit ledger audit resource'
  );
  if v_id is null then raise exception 'credit_ledger audit event was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.access', 'allowed', 'pricing_catalog_draft', v_resource, null,
    'Test pricing draft audit resource'
  );
  if v_id is null then raise exception 'pricing_catalog_draft audit event was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.access', 'allowed', 'plan_catalog_draft', v_resource, null,
    'Test plan draft audit resource'
  );
  if v_id is null then raise exception 'plan_catalog_draft audit event was not recorded'; end if;

  select count(*) into v_count
    from public.admin_audit_events
   where actor_user_id = v_actor
     and resource_type in ('credit_ledger', 'pricing_catalog_draft', 'plan_catalog_draft');
  if v_count <> 3 then raise exception 'Expected three new resource categories in audit journal'; end if;

  v_rejected := false;
  begin
    perform public.record_admin_audit_event(
      v_actor, 'admin.access', 'allowed', 'unregistered_resource', null, null,
      'Must remain rejected'
    );
  exception when invalid_parameter_value then
    v_rejected := true;
  end;
  if not v_rejected then raise exception 'Unknown audit resource category was accepted'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.support.reply', 'executed', 'support_ticket', v_resource, null,
    'Test support reply audit action'
  );
  if v_id is null then raise exception 'Support reply audit action was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.support.status.changed', 'executed', 'support_ticket', v_resource, null,
    'Test support status audit action'
  );
  if v_id is null then raise exception 'Support status audit action was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.finance.role.grant', 'requested', 'permission', v_resource, null,
    'Test finance role grant intent'
  );
  if v_id is null then raise exception 'Finance role grant audit action was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.finance.role.revoke', 'executed', 'permission', v_resource, null,
    'Test finance role revoke completion'
  );
  if v_id is null then raise exception 'Finance role revoke audit action was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.finance.request.create', 'requested', 'credit_wallet', v_resource, null,
    'Test finance request creation intent'
  );
  if v_id is null then raise exception 'Finance request creation audit action was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.finance.request.create', 'executed', 'finance_request', v_resource, null,
    'Test finance request audit resource'
  );
  if v_id is null then raise exception 'Finance request audit resource was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.finance.request.decide', 'executed', 'payment', v_resource, null,
    'Test finance request decision completion'
  );
  if v_id is null then raise exception 'Finance request decision audit action was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.finance.request.cancel', 'requested', 'payment', v_resource, null,
    'Test finance request cancellation intent'
  );
  if v_id is null then raise exception 'Finance request cancellation audit action was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.pricing.draft.create', 'requested', 'pricing_catalog_draft', null, null,
    'Test pricing draft creation intent'
  );
  if v_id is null then raise exception 'Pricing draft creation audit action was not recorded'; end if;

  v_id := public.record_admin_audit_event(
    v_actor, 'admin.plan.draft.create', 'executed', 'plan_catalog_draft', v_resource, null,
    'Test plan draft creation completion'
  );
  if v_id is null then raise exception 'Plan draft creation audit action was not recorded'; end if;

end;
$admin_audit_resource_allowlist_test$;
