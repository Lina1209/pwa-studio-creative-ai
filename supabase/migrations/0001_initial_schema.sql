-- PWA Studio — initial Supabase schema
-- Run this in Supabase SQL Editor after creating the project.
-- All user-owned rows are protected by Row Level Security (RLS).

create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.studio_projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'Новый проект',
  description text,
  project_type text not null default 'movie',
  status text not null default 'draft',
  screenplay jsonb not null default '{}'::jsonb,
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.studio_characters (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid references public.studio_projects(id) on delete cascade,
  name text not null,
  description text,
  reference_image_path text,
  voice_settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.studio_scenes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null references public.studio_projects(id) on delete cascade,
  scene_number integer not null default 1,
  title text,
  script text,
  visual_prompt text,
  duration_seconds integer,
  status text not null default 'draft',
  output_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.studio_media (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid references public.studio_projects(id) on delete set null,
  media_type text not null,
  storage_path text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists studio_projects_user_updated_idx
  on public.studio_projects(user_id, updated_at desc);
create index if not exists studio_characters_user_idx
  on public.studio_characters(user_id);
create index if not exists studio_scenes_project_idx
  on public.studio_scenes(project_id, scene_number);
create index if not exists studio_media_user_idx
  on public.studio_media(user_id, created_at desc);

alter table public.profiles enable row level security;
alter table public.studio_projects enable row level security;
alter table public.studio_characters enable row level security;
alter table public.studio_scenes enable row level security;
alter table public.studio_media enable row level security;

drop policy if exists "Users can read own profile" on public.profiles;
create policy "Users can read own profile" on public.profiles
  for select to authenticated using (auth.uid() = id);
drop policy if exists "Users can create own profile" on public.profiles;
create policy "Users can create own profile" on public.profiles
  for insert to authenticated with check (auth.uid() = id);
drop policy if exists "Users can update own profile" on public.profiles;
create policy "Users can update own profile" on public.profiles
  for update to authenticated using (auth.uid() = id) with check (auth.uid() = id);

drop policy if exists "Users manage own projects" on public.studio_projects;
create policy "Users manage own projects" on public.studio_projects
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "Users manage own characters" on public.studio_characters;
create policy "Users manage own characters" on public.studio_characters
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "Users manage own scenes" on public.studio_scenes;
create policy "Users manage own scenes" on public.studio_scenes
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "Users manage own media" on public.studio_media;
create policy "Users manage own media" on public.studio_media
  for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Profile row is created automatically for each new Auth user.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'display_name', 'Creator'));
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
