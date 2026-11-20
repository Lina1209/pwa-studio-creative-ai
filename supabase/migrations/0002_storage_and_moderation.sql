-- PWA Studio: private file storage and moderation foundations.
-- Review the bucket names and run in Supabase SQL Editor once.
-- This migration does not expose private files publicly.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('studio-media', 'studio-media', false, 262144000,
   array['image/jpeg','image/png','image/webp','image/gif','audio/mpeg','audio/wav','audio/mp4','video/mp4','video/webm','application/pdf']),
  ('studio-exports', 'studio-exports', false, 1073741824,
   array['video/mp4','video/quicktime','audio/mpeg','audio/wav','application/x-subrip'])
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Users read own studio media" on storage.objects;
create policy "Users read own studio media" on storage.objects
for select to authenticated
using (bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "Users upload own studio media" on storage.objects;
create policy "Users upload own studio media" on storage.objects
for insert to authenticated
with check (bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "Users update own studio media" on storage.objects;
create policy "Users update own studio media" on storage.objects
for update to authenticated
using (bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text)
with check (bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "Users delete own studio media" on storage.objects;
create policy "Users delete own studio media" on storage.objects
for delete to authenticated
using (bucket_id in ('studio-media','studio-exports')
  and (storage.foldername(name))[1] = auth.uid()::text);

create table if not exists public.studio_moderation_reports (
  id uuid primary key default gen_random_uuid(),
  reporter_id uuid not null references auth.users(id) on delete cascade,
  target_type text not null check (target_type in ('profile','project','character','scene','media','message')),
  target_id uuid,
  reason text not null check (char_length(reason) between 3 and 120),
  details text check (details is null or char_length(details) <= 3000),
  status text not null default 'open' check (status in ('open','reviewing','resolved','dismissed')),
  reviewed_by uuid references auth.users(id) on delete set null,
  review_note text,
  created_at timestamptz not null default now(),
  reviewed_at timestamptz
);

create table if not exists public.studio_moderation_events (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid references auth.users(id) on delete set null,
  target_user_id uuid references auth.users(id) on delete set null,
  target_type text not null,
  target_id uuid,
  action text not null,
  reason text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists studio_moderation_reports_status_idx
  on public.studio_moderation_reports(status, created_at desc);
create index if not exists studio_moderation_reports_reporter_idx
  on public.studio_moderation_reports(reporter_id, created_at desc);
create index if not exists studio_moderation_events_target_idx
  on public.studio_moderation_events(target_user_id, created_at desc);

alter table public.studio_moderation_reports enable row level security;
alter table public.studio_moderation_events enable row level security;

drop policy if exists "Users submit reports" on public.studio_moderation_reports;
create policy "Users submit reports" on public.studio_moderation_reports
for insert to authenticated with check (reporter_id = auth.uid());

drop policy if exists "Users read own reports" on public.studio_moderation_reports;
create policy "Users read own reports" on public.studio_moderation_reports
for select to authenticated using (reporter_id = auth.uid() or public.is_admin());

drop policy if exists "Admins manage moderation reports" on public.studio_moderation_reports;
create policy "Admins manage moderation reports" on public.studio_moderation_reports
for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists "Admins read moderation audit log" on public.studio_moderation_events;
create policy "Admins read moderation audit log" on public.studio_moderation_events
for select to authenticated using (public.is_admin());

drop policy if exists "Admins write moderation audit log" on public.studio_moderation_events;
create policy "Admins write moderation audit log" on public.studio_moderation_events
for insert to authenticated with check (public.is_admin());

grant select, insert on public.studio_moderation_reports to authenticated;
grant update, delete on public.studio_moderation_reports to authenticated;
grant select, insert on public.studio_moderation_events to authenticated;
