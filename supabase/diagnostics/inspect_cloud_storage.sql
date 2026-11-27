-- PWA Studio: read-only database compatibility check.
-- Run this first in Supabase SQL Editor. It changes nothing.

-- 1) Which expected application tables exist?
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_type = 'BASE TABLE'
  and table_name in (
    'profiles','projects','characters','scenes','media_assets',
    'studio_projects','studio_characters','studio_scenes','studio_media',
    'studio_prompts','voice_profiles',
    'studio_moderation_reports','studio_moderation_events'
  )
order by table_name;

-- 2) Exact columns for the project/media-related tables that exist.
select table_name, ordinal_position, column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name in (
    'profiles','projects','characters','scenes','media_assets',
    'studio_projects','studio_characters','studio_scenes','studio_media',
    'studio_prompts','voice_profiles'
  )
order by table_name, ordinal_position;

-- 3) Existing storage buckets and privacy status.
select id, name, public, file_size_limit
from storage.buckets
where id in ('studio-media','studio-exports')
order by id;

-- 4) Check whether the admin helper used by the future moderation layer exists.
select
  to_regprocedure('public.is_admin()') as is_admin_function;

-- 5) All policies on the relevant tables. Do not inspect only expected policy names:
-- permissive PostgreSQL policies combine with OR and an extra broad policy can
-- widen access even when the named owner policy is correct.
select schemaname, tablename, policyname, permissive, roles, cmd,
       qual, with_check
from pg_policies
where (schemaname = 'public' and tablename in ('projects','characters','media_assets'))
   or (schemaname = 'storage' and tablename = 'objects')
order by schemaname, tablename, policyname;

-- 6) Actual foreign keys and unique constraints that bind child rows to owners.
select
  conrelid::regclass as table_name,
  conname,
  contype,
  pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid::regclass::text in ('projects', 'characters', 'media_assets')
order by table_name::text, conname;

-- 7) Effective table grants for browser-facing roles.
select table_schema, table_name, grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name in ('projects','characters','media_assets')
  and grantee in ('anon','authenticated','service_role')
order by table_name, grantee, privilege_type;

-- 8) Confirm whether the hardening migration's composite project/owner FK exists.
select
  to_regclass('public.projects') as projects_table,
  to_regclass('public.media_assets') as media_assets_table,
  exists (
    select 1 from pg_constraint
    where conrelid = to_regclass('public.media_assets')
      and conname = 'media_assets_project_owner_fkey'
      and contype = 'f'
  ) as project_owner_fk_present;
