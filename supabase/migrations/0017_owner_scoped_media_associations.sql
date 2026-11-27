-- PWA Studio: close cross-owner project/media association gap and
-- restore the documented private-bucket owner policies.
--
-- Apply only after migrations 0005_cloud_projects_and_storage.sql and
-- 0012_character_library_media_links.sql in a disposable Supabase project.
-- This migration has NOT been applied to production.

-- A media row must belong to the same owner as its linked project.
-- The column-list SET NULL preserves the media owner when a project is deleted.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.projects'::regclass
      and conname = 'projects_id_owner_key'
  ) then
    alter table public.projects
      add constraint projects_id_owner_key unique (id, owner_id);
  end if;
end
$$;

alter table public.media_assets
  drop constraint if exists media_assets_project_id_fkey;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.media_assets'::regclass
      and conname = 'media_assets_project_owner_fkey'
  ) then
    alter table public.media_assets
      add constraint media_assets_project_owner_fkey
      foreign key (project_id, owner_id)
      references public.projects (id, owner_id)
      on delete set null (project_id);
  end if;
end
$$;

-- Recreate the named policies so re-running earlier draft migrations cannot
-- leave a weaker same-named policy in place. Other policies must still be
-- inspected: PostgreSQL permissive policies combine with OR.
drop policy if exists characters_owner on public.characters;
create policy characters_owner on public.characters
  for all to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));

drop policy if exists media_assets_owner on public.media_assets;
create policy media_assets_owner on public.media_assets
  for all to authenticated
  using (owner_id = (select auth.uid()))
  with check (owner_id = (select auth.uid()));

-- Both private buckets are supported by the documented Storage setup.
drop policy if exists "Users read own studio media" on storage.objects;
create policy "Users read own studio media" on storage.objects
  for select to authenticated
  using (
    bucket_id in ('studio-media', 'studio-exports')
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists "Users upload own studio media" on storage.objects;
create policy "Users upload own studio media" on storage.objects
  for insert to authenticated
  with check (
    bucket_id in ('studio-media', 'studio-exports')
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists "Users update own studio media" on storage.objects;
create policy "Users update own studio media" on storage.objects
  for update to authenticated
  using (
    bucket_id in ('studio-media', 'studio-exports')
    and (storage.foldername(name))[1] = (select auth.uid())::text
  )
  with check (
    bucket_id in ('studio-media', 'studio-exports')
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

drop policy if exists "Users delete own studio media" on storage.objects;
create policy "Users delete own studio media" on storage.objects
  for delete to authenticated
  using (
    bucket_id in ('studio-media', 'studio-exports')
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );

comment on constraint media_assets_project_owner_fkey on public.media_assets is
  'Prevents a media asset from referencing a project owned by another account.';
