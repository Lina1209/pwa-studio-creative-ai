\set ON_ERROR_STOP on
create extension if not exists pgcrypto;
create schema if not exists auth;

do $roles$
begin
  if not exists (select 1 from pg_roles where rolname='anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
end;
$roles$;

create table if not exists auth.users(id uuid primary key);
alter table auth.users add column if not exists raw_user_meta_data jsonb not null default '{}'::jsonb;

create table if not exists public.profiles(
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.direct_conversations(
  id uuid primary key default gen_random_uuid(),
  pair_key text not null unique,
  created_at timestamptz not null default now(),
  last_message_at timestamptz not null default now()
);
create table if not exists public.direct_conversation_participants(
  conversation_id uuid not null references public.direct_conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  joined_at timestamptz not null default now(),
  last_read_at timestamptz,
  primary key(conversation_id,user_id)
);
grant select on public.profiles to authenticated;

insert into auth.users(id) values('88888888-8888-4888-8888-888888888888')
on conflict do nothing;
insert into public.profiles(id,display_name)
values('88888888-8888-4888-8888-888888888888','Existing Creator')
on conflict(id) do update set display_name=excluded.display_name;

\i supabase/migrations/0097_creator_profiles_and_discovery.sql

drop trigger if exists test_profile_new_user on auth.users;
create trigger test_profile_new_user after insert on auth.users
for each row execute procedure public.handle_new_user();

insert into auth.users(id,raw_user_meta_data)
values('99999999-9999-4999-8999-999999999999','{"display_name":"New Creator"}'::jsonb)
on conflict do nothing;

do $$
declare
  v_username text;
  v_conversation uuid;
  v_rejected boolean := false;
begin
  select username into v_username from public.profiles
    where id='88888888-8888-4888-8888-888888888888';
  if v_username is null or v_username !~ '^creator_[0-9a-f]{8}$' then
    raise exception 'existing profile username backfill failed';
  end if;
  select username into v_username from public.profiles
    where id='99999999-9999-4999-8999-999999999999';
  if v_username is null or v_username !~ '^creator_[0-9a-f]{8}$' then
    raise exception 'new profile username generation failed';
  end if;
  if not exists(select 1 from pg_indexes where schemaname='public'
      and indexname='profiles_username_lower_unique') then
    raise exception 'case-insensitive username uniqueness index missing';
  end if;
  if not has_table_privilege('authenticated','public.profiles','select') then
    raise exception 'existing own-profile select grant unexpectedly removed';
  end if;
  if not has_table_privilege('service_role','public.profiles','update') then
    raise exception 'service role cannot update profiles';
  end if;
  update public.profiles set allow_direct_messages=false
    where id='99999999-9999-4999-8999-999999999999';
  begin
    perform public.create_direct_conversation(
      '88888888-8888-4888-8888-888888888888',
      '99999999-9999-4999-8999-999999999999'
    );
  exception when insufficient_privilege then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'recipient message privacy preference was not enforced';
  end if;
end;
$$;
