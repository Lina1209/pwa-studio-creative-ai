-- Add a curated, free profile-avatar catalog selection.
-- This migration is additive and intentionally NOT applied to any live database.
alter table public.user_profiles
  add column if not exists avatar_catalog_id text not null default 'portrait-violet',
  add column if not exists avatar_representation text not null default '2d',
  add column if not exists avatar_updated_at timestamptz not null default now();

alter table public.user_profiles
  drop constraint if exists user_profiles_avatar_representation_check;
alter table public.user_profiles
  add constraint user_profiles_avatar_representation_check
  check (avatar_representation in ('2d','3d'));

alter table public.user_profiles
  drop constraint if exists user_profiles_avatar_catalog_id_check;
alter table public.user_profiles
  add constraint user_profiles_avatar_catalog_id_check
  check (avatar_catalog_id ~ '^[a-z0-9][a-z0-9-]{1,63}$');

comment on column public.user_profiles.avatar_catalog_id is
  'Stable ID from the application curated profile-avatar catalog; never a URL or storage path.';
comment on column public.user_profiles.avatar_representation is
  'Representation of the selected catalog asset: 2d or 3d.';
comment on column public.user_profiles.avatar_updated_at is
  'Timestamp of the last profile-avatar selection change.';
