-- Minimal Supabase-compatible PostgreSQL bootstrap for disposable CI only.
-- This is NOT a production migration and contains no real user or secret data.
\set ON_ERROR_STOP on

do $$
begin
  if not exists (select 1 from pg_roles where rolname='anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
end
$$;

create schema if not exists auth;
create schema if not exists storage;

create table if not exists auth.users (
  id uuid primary key,
  email text unique
);

create or replace function auth.uid()
returns uuid
language sql stable
as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

create or replace function auth.role()
returns text
language sql stable
as $$
  select coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), current_user::text)
$$;

create table if not exists storage.buckets (
  id text primary key,
  name text not null,
  public boolean not null default false,
  file_size_limit bigint,
  allowed_mime_types text[]
);

create table if not exists storage.objects (
  id uuid primary key default gen_random_uuid(),
  bucket_id text not null references storage.buckets(id) on delete cascade,
  name text not null
);

create or replace function storage.foldername(name text)
returns text[]
language sql immutable
as $$
  select case
    when name is null or name = '' then array[]::text[]
    else (string_to_array(name, '/'))[1:greatest(array_length(string_to_array(name, '/'),1)-1,0)]
  end
$$;

grant usage on schema auth, storage to anon, authenticated, service_role;
grant select on auth.users to authenticated, service_role;
grant all on storage.buckets, storage.objects to service_role;
