-- PWA Studio: cloud movie projects and private media storage.
-- Apply this migration once in the connected Supabase SQL Editor.
-- Project payloads are stored in settings JSONB for backwards compatibility
-- with the existing Mini Movie Studio local project format.

create extension if not exists pgcrypto;

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'Новый проект',
  description text not null default '',
  project_type text not null default 'movie',
  status text not null default 'draft',
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Keep the migration safe for installations where the table was created earlier.
alter table public.projects add column if not exists owner_id uuid references auth.users(id) on delete cascade;
alter table public.projects add column if not exists title text not null default 'Новый проект';
alter table public.projects add column if not exists description text not null default '';
alter table public.projects add column if not exists project_type text not null default 'movie';
alter table public.projects add column if not exists status text not null default 'draft';
alter table public.projects add column if not exists settings jsonb not null default '{}'::jsonb;
alter table public.projects add column if not exists created_at timestamptz not null default now();
alter table public.projects add column if not exists updated_at timestamptz not null default now();

-- Existing installations may already have a projects table. Do not silently
-- leave owner_id nullable: stop with an actionable error if legacy rows need
-- an explicit ownership backfill before enabling the stricter constraint.
do $
begin
  if exists (select 1 from public.projects where owner_id is null) then
    raise exception 'Migration 0005 cannot enforce project ownership: public.projects contains rows with NULL owner_id. Backfill each row to its verified auth.users owner, then rerun this migration.';
  end if;
end;
$;

alter table public.projects alter column owner_id set not null;

create index if not exists projects_owner_type_updated_idx
  on public.projects(owner_id, project_type, updated_at desc);

alter table public.projects enable row level security;
grant select, insert, update, delete on public.projects to authenticated;

drop policy if exists "Users manage own studio projects" on public.projects;
create policy "Users manage own studio projects" on public.projects
  for all to authenticated
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

-- Private bucket. Object paths must begin with the authenticated user's UUID.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'studio-media',
  'studio-media',
  false,
  262144000,
  array[
    'image/jpeg','image/png','image/webp','image/gif',
    'audio/mpeg','audio/wav','audio/mp4','audio/ogg','audio/webm',
    'video/mp4','video/webm','video/quicktime','application/pdf'
  ]
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Users read own studio media" on storage.objects;
create policy "Users read own studio media" on storage.objects
  for select to authenticated
  using (bucket_id in ('studio-media','studio-exports') and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "Users upload own studio media" on storage.objects;
create policy "Users upload own studio media" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'studio-media' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "Users update own studio media" on storage.objects;
create policy "Users update own studio media" on storage.objects
  for update to authenticated
  using (bucket_id = 'studio-media' and (storage.foldername(name))[1] = auth.uid()::text)
  with check (bucket_id = 'studio-media' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "Users delete own studio media" on storage.objects;
create policy "Users delete own studio media" on storage.objects
  for delete to authenticated
  using (bucket_id = 'studio-media' and (storage.foldername(name))[1] = auth.uid()::text);
