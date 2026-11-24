-- PWA Studio: comprehensive READ-ONLY Supabase schema/security inventory.
-- SELECT-only. Does not read application row contents, alter schema, or change privileges.
-- Run only after confirming the SQL Editor is connected to the intended project.
-- Retain output privately; redact project/user identifiers before sharing.

-- 1) Migration ledger candidates and their columns. Do not assume a ledger format.
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

-- 2) All application tables in public: columns, types, defaults, nullability.
select table_name, ordinal_position, column_name, data_type, udt_schema, udt_name,
       is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
order by table_name, ordinal_position;

-- 3) Constraints for all public application tables.
select tc.table_name, tc.constraint_name, tc.constraint_type,
       kcu.column_name, ccu.table_name as referenced_table,
       ccu.column_name as referenced_column,
       check_constraints.check_clause
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
left join information_schema.check_constraints
  on check_constraints.constraint_catalog = tc.constraint_catalog
 and check_constraints.constraint_schema = tc.constraint_schema
 and check_constraints.constraint_name = tc.constraint_name
where tc.table_schema = 'public'
order by tc.table_name, tc.constraint_type, tc.constraint_name, kcu.ordinal_position;

-- 4) Indexes for all public application tables.
select schemaname, tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
order by tablename, indexname;

-- 5) RLS enabled/forced state for public tables and Storage objects.
select n.nspname as schema_name, c.relname as relation_name,
       c.relrowsecurity as rls_enabled, c.relforcerowsecurity as rls_forced
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname in ('public', 'storage')
  and c.relkind in ('r', 'p')
order by n.nspname, c.relname;

-- 6) All policies in public and Storage, including exact USING/WITH CHECK expressions.
select schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
from pg_policies
where schemaname in ('public', 'storage')
order by schemaname, tablename, policyname;

-- 7) Effective table-level ACL entries for public tables and Storage objects.
-- ACL expansion includes inherited defaults where relacl is NULL.
select n.nspname as schema_name, c.relname as relation_name,
       coalesce(grantee.rolname, 'PUBLIC') as grantee,
       grantor.rolname as grantor,
       acl.privilege_type, acl.is_grantable
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
cross join lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) as acl
left join pg_roles grantee on grantee.oid = acl.grantee
left join pg_roles grantor on grantor.oid = acl.grantor
where n.nspname in ('public', 'storage')
  and c.relkind in ('r', 'p', 'v', 'm', 'f')
order by n.nspname, c.relname, grantee.rolname, acl.privilege_type;

-- 8) Functions: owner, SECURITY DEFINER, volatility, configuration (including search_path),
-- and effective EXECUTE ACL. Function bodies are intentionally not selected.
select n.nspname as schema_name,
       p.proname as function_name,
       pg_get_function_identity_arguments(p.oid) as identity_arguments,
       owner_role.rolname as function_owner,
       p.prosecdef as security_definer,
       p.provolatile as volatility,
       p.proconfig as function_settings,
       coalesce(grantee.rolname, 'PUBLIC') as grantee,
       grantor.rolname as grantor,
       acl.privilege_type,
       acl.is_grantable
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
join pg_roles owner_role on owner_role.oid = p.proowner
cross join lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) as acl
left join pg_roles grantee on grantee.oid = acl.grantee
left join pg_roles grantor on grantor.oid = acl.grantor
where n.nspname in ('public', 'private', 'storage')
order by n.nspname, p.proname, identity_arguments, grantee.rolname;

-- 9) Trigger definitions and trigger-function security metadata.
select event_object_schema as table_schema,
       event_object_table as table_name,
       trigger_name, action_timing, event_manipulation,
       action_orientation, action_statement
from information_schema.triggers
where event_object_schema in ('public', 'storage')
order by event_object_schema, event_object_table, trigger_name, event_manipulation;

select n.nspname as function_schema, p.proname as trigger_function,
       pg_get_function_identity_arguments(p.oid) as identity_arguments,
       owner_role.rolname as function_owner,
       p.prosecdef as security_definer,
       p.proconfig as function_settings,
       pg_get_functiondef(p.oid) as function_definition
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
join pg_roles owner_role on owner_role.oid = p.proowner
where p.prorettype = 'trigger'::regtype
  and n.nspname in ('public', 'private', 'storage')
order by n.nspname, p.proname;

-- 10) Sequences and their ACLs (including identity/serial backing sequences).
select n.nspname as schema_name, c.relname as sequence_name,
       coalesce(grantee.rolname, 'PUBLIC') as grantee,
       grantor.rolname as grantor,
       acl.privilege_type, acl.is_grantable
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
cross join lateral aclexplode(coalesce(c.relacl, acldefault('S', c.relowner))) as acl
left join pg_roles grantee on grantee.oid = acl.grantee
left join pg_roles grantor on grantor.oid = acl.grantor
where c.relkind = 'S'
  and n.nspname in ('public', 'private')
order by n.nspname, c.relname, grantee.rolname, acl.privilege_type;

-- 11) Default privileges that affect objects created by each owner.
select owner_role.rolname as object_owner,
       n.nspname as schema_name,
       d.defaclobjtype as object_type,
       coalesce(grantee.rolname, 'PUBLIC') as grantee,
       grantor.rolname as grantor,
       acl.privilege_type,
       acl.is_grantable
from pg_default_acl d
join pg_roles owner_role on owner_role.oid = d.defaclrole
left join pg_namespace n on n.oid = d.defaclnamespace
cross join lateral aclexplode(d.defaclacl) as acl
left join pg_roles grantee on grantee.oid = acl.grantee
left join pg_roles grantor on grantor.oid = acl.grantor
order by owner_role.rolname, n.nspname, d.defaclobjtype, grantee.rolname, acl.privilege_type;

-- 12) Storage bucket configuration only; no object names or file metadata.
select id, name, public, file_size_limit, allowed_mime_types, created_at, updated_at
from storage.buckets
order by id;

-- 13) Approximate row estimates only; never selects application records/content.
select schemaname, relname as table_name, n_live_tup as estimated_live_rows
from pg_stat_user_tables
where schemaname in ('public', 'storage')
order by schemaname, relname;

-- Review checklist:
-- * Compare migration ledger entries to repository files; duplicate version 0005 is unresolved.
-- * Review every SECURITY DEFINER function for owner, auth derivation, search_path, body, and EXECUTE ACL.
-- * Verify RLS and table grants together; policies do not replace SQL privileges.
-- * Review Storage bucket privacy and every Storage policy independently.
-- * Never share secrets, JWTs, user content, prompts, object paths, or signed URLs.
