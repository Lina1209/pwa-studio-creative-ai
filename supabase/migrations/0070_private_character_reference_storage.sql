-- Private, per-user object storage for character visual references.
-- This migration is intentionally not applied to production from this PR.
begin;

insert into storage.buckets (
  id, name, public, file_size_limit, allowed_mime_types
)
values (
  'character-references',
  'character-references',
  false,
  8388608,
  array['image/png','image/jpeg','image/webp']::text[]
)
on conflict (id) do update
set public = false,
    file_size_limit = 8388608,
    allowed_mime_types = array['image/png','image/jpeg','image/webp']::text[];

drop policy if exists "Users read own character references" on storage.objects;
create policy "Users read own character references"
on storage.objects for select to authenticated
using (
  bucket_id = 'character-references'
  and (storage.foldername(name))[1] = (select auth.uid())::text
);

drop policy if exists "Users upload own character references" on storage.objects;
create policy "Users upload own character references"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'character-references'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and lower(storage.extension(name)) in ('png','jpg','jpeg','webp')
);

drop policy if exists "Users update own character references" on storage.objects;
create policy "Users update own character references"
on storage.objects for update to authenticated
using (
  bucket_id = 'character-references'
  and (storage.foldername(name))[1] = (select auth.uid())::text
)
with check (
  bucket_id = 'character-references'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and lower(storage.extension(name)) in ('png','jpg','jpeg','webp')
);

drop policy if exists "Users delete own character references" on storage.objects;
create policy "Users delete own character references"
on storage.objects for delete to authenticated
using (
  bucket_id = 'character-references'
  and (storage.foldername(name))[1] = (select auth.uid())::text
);

commit;
