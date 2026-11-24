-- PWA Studio: read-only project / asset / Storage security inventory.
-- This script contains SELECT statements only. It does not apply migrations or change data/policies.
-- Run in Supabase SQL Editor and retain the results for a reviewed reconciliation plan.

-- 1) Migration-ledger locations and columns (do not assume a ledger table/version layout).
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

-- 2) Relevant application tables and exact columns.
select table_schema, table_name, ordinal_position, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
  and table_name in (
    'profiles','user_profiles','projects',
    'studio_projects','studio_characters','studio_scenes','studio_media',
    'characters','scenes','media_assets'
  )
order by table_name, ordinal_position;

-- 3) Constraints and foreign keys for those tables.
select tc.table_name, tc.constraint_name, tc.constraint_type,
       kcu.column_name, ccu.table_name as foreign_table_name,
       ccu.column_name as foreign_column_name
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
  and tc.table_name in (
    'profiles','user_profiles','projects',
    'studio_projects','studio_characters','studio_scenes','studio_media',
    'characters','scenes','media_assets'
  )
order by tc.table_name, tc.constraint_type, tc.constraint_name, kcu.ordinal_position;

-- 4) Index definitions for relevant tables.
select schemaname, tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename in (
    'profiles','user_profiles','projects',
    'studio_projects','studio_characters','studio_scenes','studio_media',
    'characters','scenes','media_assets'
  )
order by tablename, indexname;

-- 5) RLS enabled/forced flags.
select n.nspname as schema_name, c.relname as table_name,
       c.relrowsecurity as rls_enabled, c.relforcerowsecurity as rls_forced
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname in ('public','storage')
  and c.relkind = 'r'
  and (
    c.relname in (
      'profiles','user_profiles','projects',
      'studio_projects','studio_characters','studio_scenes','studio_media',
      'characters','scenes','media_assets'
    )
    or (n.nspname = 'storage' and c.relname = 'objects')
  )
order by n.nspname, c.relname;

-- 6) Policies for application tables and Storage objects.
select schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
from pg_policies
where (schemaname = 'public' and tablename in (
    'profiles','user_profiles','projects',
    'studio_projects','studio_characters','studio_scenes','studio_media',
    'characters','scenes','media_assets'
  ))
   or (schemaname = 'storage' and tablename = 'objects')
order by schemaname, tablename, policyname;

-- 7) Explicit table grants for relevant tables.
select table_schema, table_name, grantee, privilege_type, is_grantable
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in (
    'profiles','user_profiles','projects',
    'studio_projects','studio_characters','studio_scenes','studio_media',
    'characters','scenes','media_assets'
  )
order by table_name, grantee, privilege_type;

-- 8) Live Storage bucket settings (private/public, limits, MIME allowlist).
select id, name, public, file_size_limit, allowed_mime_types, created_at, updated_at
from storage.buckets
where id in ('studio-media','studio-exports')
order by id;

-- 9) Approximate row estimates only; no user content is selected.
select schemaname, relname as table_name, n_live_tup as estimated_live_rows
from pg_stat_user_tables
where schemaname = 'public'
  and relname in (
    'profiles','user_profiles','projects',
    'studio_projects','studio_characters','studio_scenes','studio_media',
    'characters','scenes','media_assets'
  )
order by relname;

-- Review note:
-- A policy listing is not a substitute for two-account integration tests.
-- Do not paste credentials, access tokens, signed URLs, prompts, or private media in audit notes.
