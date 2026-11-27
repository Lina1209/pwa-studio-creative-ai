-- PWA Studio Character Library: read-only post-migration verification.
-- Run ONLY in a disposable Supabase test project after applying migration 0012.
-- This script does not insert, update, or delete data.

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
        AND pg_get_constraintdef(c.oid) ILIKE
          'FOREIGN KEY (character_id, owner_id) REFERENCES characters(id, owner_id)%'
    ),
    'FK (character_id, owner_id) -> characters(id, owner_id)'
  UNION ALL
  SELECT
    'character composite unique key exists',
    EXISTS (
      SELECT 1 FROM pg_constraint c
      WHERE c.conrelid='public.characters'::regclass
        AND c.contype='u'
        AND pg_get_constraintdef(c.oid) ILIKE 'UNIQUE (id, owner_id)%'
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
    (SELECT relrowsecurity FROM pg_class WHERE oid='public.characters'::regclass),
    'pg_class.relrowsecurity = true'
  UNION ALL
  SELECT
    'media_assets RLS enabled',
    (SELECT relrowsecurity FROM pg_class WHERE oid='public.media_assets'::regclass),
    'pg_class.relrowsecurity = true'
  UNION ALL
  SELECT
    'characters owner policy exists',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='public' AND tablename='characters'
        AND policyname='characters_owner'
        AND qual ILIKE '%owner_id%auth.uid()%'
        AND with_check ILIKE '%owner_id%auth.uid()%'
    ),
    'characters_owner USING and WITH CHECK owner_id = auth.uid()'
  UNION ALL
  SELECT
    'media_assets owner policy exists',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='public' AND tablename='media_assets'
        AND policyname='media_assets_owner'
        AND qual ILIKE '%owner_id%auth.uid()%'
        AND with_check ILIKE '%owner_id%auth.uid()%'
    ),
    'media_assets_owner USING and WITH CHECK owner_id = auth.uid()'
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
    'studio-media SELECT policy exists',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='storage' AND tablename='objects'
        AND policyname='Users read own studio media'
        AND qual ILIKE '%studio-media%'
        AND qual ILIKE '%auth.uid()%'
    ),
    'Users read own studio media, scoped by bucket and auth.uid()'
  UNION ALL
  SELECT
    'studio-media INSERT policy exists',
    EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname='storage' AND tablename='objects'
        AND policyname='Users upload own studio media'
        AND with_check ILIKE '%studio-media%'
        AND with_check ILIKE '%auth.uid()%'
    ),
    'Users upload own studio media, scoped by bucket and auth.uid()'
)
SELECT
  CASE WHEN passed THEN 'PASS' ELSE 'FAIL' END AS result,
  check_name,
  expected
FROM checks
ORDER BY passed, check_name;
