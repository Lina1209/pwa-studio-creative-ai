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
