-- PWA Studio: character library media-association schema foundation.
-- Draft feature-branch migration only. Never run against production as part of
-- this development workflow. Apply only after a separate migration review and
-- explicit deployment approval.
--
-- IMPORTANT: this migration creates database primitives; it does NOT enable
-- browser cloud sync, an importer, or cross-device library restore. The current
-- Character Library UI remains local-first (localStorage + IndexedDB).
-- Later migrations add server-mediated upload, verification, and cleanup
-- lifecycle controls. Do not infer that direct browser Storage access is safe.
--
-- Characters keep their visual passport in reference_data (JSONB).
-- Individual reference/avatar files are represented by media_assets rows.
-- A composite foreign key guarantees that an asset and its character have
-- the same owner_id; this prevents cross-account character associations.

create extension if not exists pgcrypto;

create table if not exists public.characters (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  description text,
  avatar_url text,
  reference_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.media_assets (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid references public.projects(id) on delete set null,
  file_name text not null,
  file_type text,
  storage_path text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- Additive column: NULL means the asset is not attached to a character.
alter table public.media_assets
  add column if not exists character_id uuid;

-- The composite key is intentional: a plain FK to characters(id) would allow
-- an owner to associate their media row with another user's character.
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.characters'::regclass
      and conname = 'characters_id_owner_key'
  ) then
    alter table public.characters
      add constraint characters_id_owner_key unique (id, owner_id);
  end if;
end
$$;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.media_assets'::regclass
      and conname = 'media_assets_character_owner_fkey'
  ) then
    alter table public.media_assets
      add constraint media_assets_character_owner_fkey
      foreign key (character_id, owner_id)
      references public.characters (id, owner_id)
      on delete restrict;
  end if;
end
$$;

create index if not exists idx_media_assets_owner_character_created
  on public.media_assets (owner_id, character_id, created_at desc)
  where character_id is not null;

-- Preserve the existing owner-only access model on both tables.
alter table public.characters enable row level security;
alter table public.media_assets enable row level security;

grant select, insert, update, delete on public.characters to authenticated;
grant select, insert, update, delete on public.media_assets to authenticated;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'characters'
      and policyname = 'characters_owner'
  ) then
    create policy characters_owner on public.characters
      for all to authenticated
      using (owner_id = auth.uid())
      with check (owner_id = auth.uid());
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'media_assets'
      and policyname = 'media_assets_owner'
  ) then
    create policy media_assets_owner on public.media_assets
      for all to authenticated
      using (owner_id = auth.uid())
      with check (owner_id = auth.uid());
  end if;
end
$$;

comment on column public.characters.reference_data is
  'Character visual passport metadata; reference image files live in private studio-media storage and are indexed in media_assets.';

comment on column public.media_assets.character_id is
  'Optional character association. Composite FK with owner_id prevents cross-owner links.';

comment on column public.media_assets.storage_path is
  'Stable object path in the private studio-media bucket; do not store expiring signed URLs.';
