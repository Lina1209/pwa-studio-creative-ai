-- Read-only preflight for migration 0013.
-- Run only in a non-production SQL editor first. This script performs no writes.

select
  to_regclass('public.generation_jobs') as generation_jobs_table,
  to_regclass('public.generation_job_outbox') as generation_job_outbox_table,
  to_regclass('public.generation_job_outbox_id_seq') as outbox_sequence;

select
  c.relname as table_name,
  c.relrowsecurity as rls_enabled,
  c.relforcerowsecurity as force_rls
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relname in ('generation_jobs','generation_job_outbox')
order by c.relname;

select
  tablename,
  policyname,
  roles,
  cmd,
  qual,
  with_check
from pg_policies
where schemaname = 'public'
  and tablename in ('generation_jobs','generation_job_outbox')
order by tablename, policyname;

select
  table_name,
  grantee,
  privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in ('generation_jobs','generation_job_outbox')
order by table_name, grantee, privilege_type;

select
  conrelid::regclass as table_name,
  conname,
  contype,
  pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid in (
  coalesce(to_regclass('public.generation_jobs'), 'pg_class'::regclass),
  coalesce(to_regclass('public.generation_job_outbox'), 'pg_class'::regclass)
)
order by table_name, conname;
