-- Fault-injection integration test for migration 0016.
-- RUN ONLY against a disposable Supabase project with migration 0005 and 0016 applied.
-- Requires psql variables:
--   moderator_id = existing auth.users UUID with admin identity
--   target_user_id = different existing auth.users UUID
--   report_id = existing pending public.user_reports UUID
--   suspension_id = existing active public.user_suspensions UUID
-- Example:
-- psql "$DISPOSABLE_DATABASE_URL" -v moderator_id=... -v target_user_id=... \
--   -v report_id=... -v suspension_id=... -f 0016_moderation_atomic_audit_rollback.sql
--
-- This test installs a temporary-in-transaction trigger that rejects the audit INSERT.
-- Each RPC must roll back its preceding state mutation. The outer transaction is rolled back.

begin;

select set_config('pwa.test.moderator_id', :'moderator_id', true);
select set_config('pwa.test.target_user_id', :'target_user_id', true);
select set_config('pwa.test.report_id', :'report_id', true);
select set_config('pwa.test.suspension_id', :'suspension_id', true);

create or replace function public.pwa_test_fail_audit_insert_0016()
returns trigger
language plpgsql
as $$
begin
  if new.action = current_setting('pwa.test.fail_action', true) then
    raise exception 'Injected audit insert failure for rollback test' using errcode = 'PZ001';
  end if;
  return new;
end;
$$;

drop trigger if exists pwa_test_fail_audit_insert_0016 on public.admin_audit_log;
create trigger pwa_test_fail_audit_insert_0016
before insert on public.admin_audit_log
for each row execute function public.pwa_test_fail_audit_insert_0016();

do $$
declare
  v_report_id uuid := current_setting('pwa.test.report_id')::uuid;
  v_moderator_id uuid := current_setting('pwa.test.moderator_id')::uuid;
  v_target_user_id uuid := current_setting('pwa.test.target_user_id')::uuid;
  v_suspension_id uuid := current_setting('pwa.test.suspension_id')::uuid;
  v_status text;
  v_revoked_at timestamptz;
  v_count_before bigint;
  v_count_after bigint;
begin
  if not exists (select 1 from public.user_reports where id=v_report_id and status='pending') then
    raise exception 'report_id must identify an existing pending report';
  end if;
  if not exists (select 1 from public.user_suspensions where id=v_suspension_id and revoked_at is null) then
    raise exception 'suspension_id must identify an existing active suspension';
  end if;

  perform set_config('pwa.test.fail_action', 'report.reviewed', true);
  begin
    perform public.pwa_review_user_report(v_report_id, v_moderator_id, 'resolved', 'rollback test');
    raise exception 'Expected report audit failure was not raised';
  exception when sqlstate 'PZ001' then
    null;
  end;
  select status into v_status from public.user_reports where id=v_report_id;
  if v_status <> 'pending' then
    raise exception 'Report state was not rolled back; found status=%', v_status;
  end if;

  select count(*) into v_count_before
    from public.user_suspensions
   where user_id=v_target_user_id and created_by=v_moderator_id and reason='Atomic audit rollback test';
  perform set_config('pwa.test.fail_action', 'user.suspended', true);
  begin
    perform public.pwa_create_user_suspension(
      v_target_user_id, v_moderator_id, 'Atomic audit rollback test', 'community', null
    );
    raise exception 'Expected suspension audit failure was not raised';
  exception when sqlstate 'PZ001' then
    null;
  end;
  select count(*) into v_count_after
    from public.user_suspensions
   where user_id=v_target_user_id and created_by=v_moderator_id and reason='Atomic audit rollback test';
  if v_count_after <> v_count_before then
    raise exception 'Suspension insert was not rolled back';
  end if;

  perform set_config('pwa.test.fail_action', 'user.suspension_revoked', true);
  begin
    perform public.pwa_revoke_user_suspension(v_suspension_id, v_moderator_id);
    raise exception 'Expected revoke audit failure was not raised';
  exception when sqlstate 'PZ001' then
    null;
  end;
  select revoked_at into v_revoked_at from public.user_suspensions where id=v_suspension_id;
  if v_revoked_at is not null then
    raise exception 'Suspension revocation was not rolled back';
  end if;

  if not has_function_privilege('service_role',
       'public.pwa_review_user_report(uuid,uuid,text,text)', 'EXECUTE') then
    raise exception 'service_role cannot execute report review RPC';
  end if;
  if has_function_privilege('authenticated',
       'public.pwa_review_user_report(uuid,uuid,text,text)', 'EXECUTE') then
    raise exception 'authenticated unexpectedly has report review RPC execution';
  end if;
end;
$$;

rollback;
