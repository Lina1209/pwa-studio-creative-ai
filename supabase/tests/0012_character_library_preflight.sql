-- PWA Studio Character Library: read-only post-migration verification.
-- Run ONLY in a disposable Supabase test project after applying migration 0012.
-- This script does not insert, update, or delete data.
-- Storage policy names are intentionally not hard-coded: installations may use
-- different policy labels, so the checks inspect the actual policy expressions.

WITH checks AS (
  SELECT
    'media_assets.character_id exists' AS check_name,
    EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema='public' AND table_name='media_assets'
        AND column_name='character_id' AND data_type='uuid'
    ) AS passed,
    'public.media_assets.character_id must be uuid' AS expected
  UNION ALL
  SELECT
    'composite owner-safe foreign key exists',
    EXISTS (
      SELECT 1
      FROM pg_constraint c
      WHERE c.conrelid='public.media_assets'::regclass
        AND c.confrelid='public.characters'::regclass
        AND c.contype='f'
        AND lower(regexp_replace(replace(pg_get_constraintdef(c.oid),'public.',''),'[[:space:]]','','g')) LIKE
          'foreignkey(character_id,owner_id)referencescharacters(id,owner_id)%'
    ),
    'FK (character_id, owner_id) -> characters(id, owner_id)'
  UNION ALL
  SELECT
    'character composite unique key exists',
    EXISTS (
      SELECT 1 FROM pg_constraint c
      WHERE c.conrelid='public.characters'::regclass
        AND c.contype='u'
        AND lower(regexp_replace(replace(pg_get_constraintdef(c.oid),'public.',''),'[[:space:]]','','g')) LIKE 'unique(id,owner_id)%'
    ),
    'UNIQUE (id, owner_id)'
  UNION ALL
  SELECT
    'character media lookup index exists',
    to_regclass('public.idx_media_assets_owner_character_created') IS NOT NULL,
    'idx_media_assets_owner_character_created'
  UNION ALL
  SELECT
    'characters RLS enabled',
    COALESCE((SELECT relrowsecurity FROM pg_class WHERE oid='public.characters'::regclass),false),
    'pg_class.relrowsecurity = true'
  UNION ALL
  SELECT
    'media_assets RLS enabled',
    COALESCE((SELECT relrowsecurity FROM pg_class WHERE oid='public.media_assets'::regclass),false),
    'pg_class.relrowsecurity = true'
  UNION ALL
  SELECT
    'characters owner policy exists',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='public' AND tablename='characters'
        AND roles @> ARRAY['authenticated']::name[]
        AND cmd='ALL'
        AND qual ILIKE '%owner_id%auth.uid()%'
        AND with_check ILIKE '%owner_id%auth.uid()%'
    ),
    'authenticated ALL policy with owner_id = auth.uid() in USING and WITH CHECK'
  UNION ALL
  SELECT
    'media_assets owner policy exists',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='public' AND tablename='media_assets'
        AND roles @> ARRAY['authenticated']::name[]
        AND cmd='ALL'
        AND qual ILIKE '%owner_id%auth.uid()%'
        AND with_check ILIKE '%owner_id%auth.uid()%'
    ),
    'authenticated ALL policy with owner_id = auth.uid() in USING and WITH CHECK'
  UNION ALL
  SELECT
    'studio-media bucket is private',
    EXISTS (
      SELECT 1 FROM storage.buckets
      WHERE id='studio-media' AND public=false
    ),
    'storage.buckets: id=studio-media, public=false'
  UNION ALL
  SELECT
    'studio-media SELECT policy is owner-folder scoped',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='storage' AND tablename='objects'
        AND cmd='SELECT'
        AND qual ILIKE '%studio-media%'
        AND qual ILIKE '%auth.uid()%'
        AND qual ILIKE '%foldername%'
    ),
    'SELECT policy restricts bucket studio-media and first folder to auth.uid()'
  UNION ALL
  SELECT
    'studio-media INSERT policy is owner-folder scoped',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='storage' AND tablename='objects'
        AND cmd='INSERT'
        AND with_check ILIKE '%studio-media%'
        AND with_check ILIKE '%auth.uid()%'
        AND with_check ILIKE '%foldername%'
    ),
    'INSERT policy restricts bucket studio-media and first folder to auth.uid()'
  UNION ALL
  SELECT
    'studio-media UPDATE policy is owner-folder scoped',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='storage' AND tablename='objects'
        AND cmd='UPDATE'
        AND roles @> ARRAY['authenticated']::name[]
        AND qual ILIKE '%studio-media%'
        AND qual ILIKE '%auth.uid()%'
        AND qual ILIKE '%foldername%'
        AND with_check ILIKE '%studio-media%'
        AND with_check ILIKE '%auth.uid()%'
        AND with_check ILIKE '%foldername%'
    ),
    'authenticated UPDATE policy restricts USING and WITH CHECK to owner folder'
  UNION ALL
  SELECT
    'studio-media DELETE policy is owner-folder scoped',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='storage' AND tablename='objects'
        AND cmd='DELETE'
        AND roles @> ARRAY['authenticated']::name[]
        AND qual ILIKE '%studio-media%'
        AND qual ILIKE '%auth.uid()%'
        AND qual ILIKE '%foldername%'
    ),
    'authenticated DELETE policy restricts bucket studio-media and first folder to auth.uid()'
)
SELECT
  CASE WHEN passed THEN 'PASS' ELSE 'FAIL' END AS result,
  check_name,
  expected
FROM checks
ORDER BY passed, check_name;
