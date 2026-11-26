-- PWA Studio: READ-ONLY Supabase security reconciliation
-- This file contains SELECT statements only. It does not modify schema, data, grants, policies, or storage.
-- Run in the SQL Editor of the exact Supabase project being audited.

-- 1) Confirm non-secret project/database context.
select current_database() as database_name,
       current_user as sql_editor_role,
       current_setting('server_version') as postgres_version,
       now() as checked_at;

-- 2) Find migration ledger candidates and their columns.
select table_schema, table_name, column_name, data_type
from information_schema.columns
where (table_name = 'schema_migrations'
       or table_name ilike '%migration%')
  and table_schema not in ('pg_catalog', 'information_schema')
order by table_schema, table_name, ordinal_position;

-- 3) Public tables: RLS state, policies, and grants.
select n.nspname as schema_name,
       c.relname as table_name,
       c.relrowsecurity as rls_enabled,
       c.relforcerowsecurity as rls_forced
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname in ('public', 'storage')
  and c.relkind in ('r','p')
order by n.nspname, c.relname;

select schemaname, tablename, policyname, permissive,
       roles, cmd, qual, with_check
from pg_policies
where schemaname in ('public', 'storage')
order by schemaname, tablename, policyname;

select table_schema, table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema in ('public', 'storage')
order by table_schema, table_name, grantee, privilege_type;

-- 4) Functions: owner, SECURITY DEFINER, search_path/config, and explicit ACL entries.
select n.nspname as schema_name,
       p.proname as function_name,
       pg_get_function_identity_arguments(p.oid) as arguments,
       owner_role.rolname as owner_name,
       p.prosecdef as security_definer,
       p.proconfig as function_settings,
       coalesce(array_to_string(p.proacl, ', '), '(default ACL)') as acl
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
join pg_roles owner_role on owner_role.oid = p.proowner
where n.nspname = 'public'
order by p.proname, arguments;

-- 5) Effective EXECUTE grants for public-schema functions.
select routine_schema, routine_name, specific_name,
       grantee, privilege_type, is_grantable
from information_schema.routine_privileges
where routine_schema = 'public'
order by routine_name, specific_name, grantee;

-- 6) Default privileges and sequence grants.
select pg_get_userbyid(d.defaclrole) as owner_role,
       n.nspname as schema_name,
       d.defaclobjtype as object_type,
       d.defaclacl as default_acl
from pg_default_acl d
left join pg_namespace n on n.oid = d.defaclnamespace
order by owner_role, schema_name, object_type;

select sequence_schema, sequence_name, grantee, privilege_type
from information_schema.role_usage_grants
where object_type = 'SEQUENCE'
  and sequence_schema in ('public', 'storage')
order by sequence_schema, sequence_name, grantee, privilege_type;

-- 7) Non-internal triggers on public tables.
select event_object_schema, event_object_table, trigger_name,
       action_timing, event_manipulation, action_statement
from information_schema.triggers
where event_object_schema = 'public'
order by event_object_table, trigger_name;

-- 8) Storage buckets metadata (no file names or file contents).
select id, name, public, file_size_limit, allowed_mime_types
from storage.buckets
order by name;
