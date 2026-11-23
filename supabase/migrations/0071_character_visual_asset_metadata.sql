-- Account-owned metadata for character and scene visual-library assets.
begin;
create table if not exists public.character_visual_assets (
  user_id uuid not null references auth.users(id) on delete cascade,
  asset_id text not null,
  asset jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, asset_id),
  constraint character_visual_assets_asset_object check (jsonb_typeof(asset) = 'object'),
  constraint character_visual_assets_asset_size check (octet_length(asset::text) <= 24000)
);
alter table public.character_visual_assets enable row level security;
drop policy if exists "Users read own visual assets" on public.character_visual_assets;
create policy "Users read own visual assets" on public.character_visual_assets
for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists "Users create own visual assets" on public.character_visual_assets;
create policy "Users create own visual assets" on public.character_visual_assets
for insert to authenticated with check (user_id = (select auth.uid()));
drop policy if exists "Users update own visual assets" on public.character_visual_assets;
create policy "Users update own visual assets" on public.character_visual_assets
for update to authenticated using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));
drop policy if exists "Users delete own visual assets" on public.character_visual_assets;
create policy "Users delete own visual assets" on public.character_visual_assets
for delete to authenticated using (user_id = (select auth.uid()));
grant select, insert, update, delete on public.character_visual_assets to authenticated;
commit;
