-- Versioned tariff drafts are review artifacts only. They do not affect live quotes.
create table if not exists public.pricing_catalog_drafts (
  id uuid primary key default gen_random_uuid(),
  version text not null unique check (char_length(version) between 1 and 80),
  catalog_json jsonb not null check (
    jsonb_typeof(catalog_json) = 'object'
    and catalog_json ? 'version'
    and catalog_json ? 'rules'
    and octet_length(catalog_json::text) <= 65536
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint pricing_catalog_draft_version_matches check (catalog_json->>'version' = version)
);
create index if not exists pricing_catalog_drafts_created_idx
  on public.pricing_catalog_drafts(created_at desc, id desc);
alter table public.pricing_catalog_drafts enable row level security;
revoke all on public.pricing_catalog_drafts from public, anon, authenticated;
grant select, insert on public.pricing_catalog_drafts to service_role;

create or replace function public.prevent_pricing_catalog_draft_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'pricing catalog drafts are immutable; create a new version' using errcode = '55000';
end;
$$;
drop trigger if exists pricing_catalog_drafts_immutable on public.pricing_catalog_drafts;
create trigger pricing_catalog_drafts_immutable
before update or delete on public.pricing_catalog_drafts
for each row execute function public.prevent_pricing_catalog_draft_mutation();

comment on table public.pricing_catalog_drafts is
  'Immutable admin-only tariff draft versions. Drafts are not used by live pricing quotes.';
