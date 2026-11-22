-- PWA Studio: private object storage foundation only.
-- This migration does NOT create moderation reports, bans, appeals, or audit-log tables.
-- Safe to run after the Supabase project has been created.
-- Buckets remain PRIVATE. Every object path must start with the authenticated user's UUID.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('studio-media', 'studio-media', false, 262144000,
   array['image/jpeg','image/png','image/webp','image/gif','audio/mpeg','audio/wav','audio/mp4','audio/ogg','audio/webm','video/mp4','video/webm','application/pdf']),
  ('studio-exports', 'studio-exports', false, 1073741824,
   array['video/mp4','video/quicktime','audio/mpeg','audio/wav','application/x-subrip'])
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Users read own studio media" on storage.objects;
create policy "Users read own studio media" on storage.objects
for select to authenticated
using (
  bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "Users upload own studio media" on storage.objects;
create policy "Users upload own studio media" on storage.objects
for insert to authenticated
with check (
  bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "Users update own studio media" on storage.objects;
create policy "Users update own studio media" on storage.objects
for update to authenticated
using (
  bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text
)
with check (
  bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "Users delete own studio media" on storage.objects;
create policy "Users delete own studio media" on storage.objects
for delete to authenticated
using (
  bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text
);
