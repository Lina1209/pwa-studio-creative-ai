-- Read-only inspection for migration 0014 privileged queue RPCs.
-- This is a catalogue check only; it does not execute functions or prove race safety.

select
  p.proname as function_name,
  pg_get_function_identity_arguments(p.oid) as arguments,
  p.prosecdef as security_definer,
  p.proconfig as function_settings
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
  and p.proname in (
    'claim_generation_outbox',
    'ack_generation_outbox',
    'claim_generation_job',
    'heartbeat_generation_job',
    'complete_generation_job',
    'fail_generation_job',
    'request_generation_job_cancel',
    'finish_generation_job_cancel',
    'recover_expired_generation_jobs',
    'record_generation_submission_outcome'
  )
order by p.proname;

select
  routine_name,
  grantee,
  privilege_type
from information_schema.routine_privileges
where specific_schema = 'public'
  and routine_name in (
    'claim_generation_outbox',
    'ack_generation_outbox',
    'claim_generation_job',
    'heartbeat_generation_job',
    'complete_generation_job',
    'fail_generation_job',
    'request_generation_job_cancel',
    'finish_generation_job_cancel',
    'recover_expired_generation_jobs',
    'record_generation_submission_outcome'
  )
order by routine_name, grantee, privilege_type;

select
  p.proname as function_name,
  r.rolname as grantee,
  has_function_privilege(r.rolname, p.oid, 'EXECUTE') as can_execute
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
cross join pg_roles r
where n.nspname = 'public'
  and p.proname in (
    'claim_generation_outbox',
    'ack_generation_outbox',
    'claim_generation_job',
    'heartbeat_generation_job',
    'complete_generation_job',
    'fail_generation_job',
    'request_generation_job_cancel',
    'finish_generation_job_cancel',
    'recover_expired_generation_jobs',
    'record_generation_submission_outcome'
  )
  and r.rolname in ('anon','authenticated','service_role')
order by function_name, grantee;

select
  column_name,
  data_type,
  is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'generation_job_outbox'
  and column_name in ('claimed_by','dead_lettered_at','last_error_code')
order by column_name;

select
  column_name,
  data_type,
  is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'media_assets'
  and column_name in ('id','owner_id','storage_path')
order by column_name;
