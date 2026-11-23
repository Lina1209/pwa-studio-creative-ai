-- Public-facing community profiles. Private fields (email/auth metadata) are never exposed.
create table if not exists public.user_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  username text not null unique,
  display_name text not null default 'Новый участник',
  bio text not null default '',
  visibility text not null default 'public' check (visibility in ('public','private')),
  show_in_directory boolean not null default true,
  avatar_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_profiles_username_format check (username ~ '^[a-z0-9_.]{3,24}$'),
  constraint user_profiles_display_name_length check (char_length(display_name) between 2 and 40),
  constraint user_profiles_bio_length check (char_length(bio) <= 500)
);
create index if not exists user_profiles_directory_idx
  on public.user_profiles (show_in_directory, visibility, username);
alter table public.user_profiles enable row level security;
revoke all on public.user_profiles from anon, authenticated;
grant select on public.user_profiles to authenticated;
grant select, insert, update on public.user_profiles to service_role;
drop policy if exists "Users read visible community profiles" on public.user_profiles;
create policy "Users read visible community profiles" on public.user_profiles
  for select to authenticated
  using ((visibility = 'public' and show_in_directory = true) or auth.uid() = user_id);
comment on table public.user_profiles is 'Minimal public community profile; private auth data is never stored here.';
