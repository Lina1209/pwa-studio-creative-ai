-- PWA Studio: expanded read-only platform security inventory.
-- SELECT-only. Does not read application row contents or mutate schema/data/security.
-- Run only after confirming the SQL Editor is connected to the intended project.
-- Review function bodies separately in repository source / Supabase definitions.

-- 1) All public base tables and RLS enforcement flags.
select n.nspname as schema_name, c.relname as table_name,
       c.relrowsecurity as rls_enabled, c.relforcerowsecurity as rls_forced,
       pg_get_userbyid(c.relowner) as table_owner
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind in ('r','p')
order by c.relname;

-- 2) Policies for every public table and Storage objects.
select schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'public'
   or (schemaname = 'storage' and tablename = 'objects')
order by schemaname, tablename, policyname;

-- 3) Explicit table privileges for all public tables.
select table_schema, table_name, grantee, privilege_type, is_grantable
from information_schema.role_table_grants
where table_schema = 'public'
order by table_name, grantee, privilege_type;

-- 4) Constraints for all public tables (including foreign-key ownership relationships).
select tc.table_name, tc.constraint_name, tc.constraint_type,
       kcu.column_name, ccu.table_name as referenced_table,
       ccu.column_name as referenced_column
from information_schema.table_constraints tc
left join information_schema.key_column_usage kcu
  on tc.constraint_catalog = kcu.constraint_catalog
 and tc.constraint_schema = kcu.constraint_schema
 and tc.constraint_name = kcu.constraint_name
 and tc.table_name = kcu.table_name
left join information_schema.constraint_column_usage ccu
  on tc.constraint_catalog = ccu.constraint_catalog
 and tc.constraint_schema = ccu.constraint_schema
 and tc.constraint_name = ccu.constraint_name
where tc.table_schema = 'public'
order by tc.table_name, tc.constraint_type, tc.constraint_name, kcu.ordinal_position;

-- 5) Index definitions for all public tables.
select schemaname, tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
order by tablename, indexname;

-- 6) Public functions: owner, SECURITY DEFINER, search_path config, and effective ACL.
-- Function source is intentionally not selected here; review definitions separately.
select n.nspname as schema_name,
       p.proname as function_name,
       pg_get_function_identity_arguments(p.oid) as identity_arguments,
       pg_get_userbyid(p.proowner) as function_owner,
       p.prosecdef as security_definer,
       p.proconfig as function_settings,
       coalesce(array_to_string(p.proacl, ', '), '(default ACL)') as function_acl
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public'
order by p.proname, identity_arguments;

-- 7) Triggers on public tables and their invoked functions.
select event_object_table as table_name,
       trigger_name,
       action_timing,
       event_manipulation,
       action_orientation,
       action_statement
from information_schema.triggers
where trigger_schema = 'public'
order by event_object_table, trigger_name, event_manipulation;

-- 8) Sequences and their owners.
select sequence_schema, sequence_name, data_type,
       start_value, minimum_value, maximum_value, increment, cycle_option
from information_schema.sequences
where sequence_schema = 'public'
order by sequence_name;

-- 9) Storage bucket configuration, including MIME allowlists.
select id, name, public, file_size_limit, allowed_mime_types,
       created_at, updated_at
from storage.buckets
order by id;

-- 10) Candidate migration ledger locations/columns. Do not assume a framework.
select table_schema, table_name
from information_schema.tables
where table_type = 'BASE TABLE'
  and (table_name ilike '%migration%' or table_schema = 'supabase_migrations')
order by table_schema, table_name;

select table_schema, table_name, ordinal_position, column_name, data_type, is_nullable
from information_schema.columns
where table_name ilike '%migration%'
   or table_schema = 'supabase_migrations'
order by table_schema, table_name, ordinal_position;

-- Safety: this script deliberately does not select user profile rows, messages,
-- prompts, project JSON, media metadata, storage object names, or file contents.
