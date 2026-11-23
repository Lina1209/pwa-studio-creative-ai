-- Public creator identity and privacy-aware discovery.
alter table public.profiles
  add column if not exists username text,
  add column if not exists bio text not null default '',
  add column if not exists profile_visibility text not null default 'private',
  add column if not exists discoverable boolean not null default false,
  add column if not exists allow_direct_messages boolean not null default true;

update public.profiles
set username = 'creator_' || substr(replace(id::text, '-', ''), 1, 8)
where username is null or btrim(username) = '';

alter table public.profiles alter column username set not null;

alter table public.profiles
  drop constraint if exists profiles_username_format,
  add constraint profiles_username_format
    check (username ~ '^[a-z0-9_]{3,24}$'),
  drop constraint if exists profiles_display_name_length,
  add constraint profiles_display_name_length
    check (display_name is null or char_length(btrim(display_name)) between 2 and 40),
  drop constraint if exists profiles_bio_length,
  add constraint profiles_bio_length
    check (char_length(bio) <= 160),
  drop constraint if exists profiles_visibility_values,
  add constraint profiles_visibility_values
    check (profile_visibility in ('public', 'private'));

create unique index if not exists profiles_username_lower_unique
  on public.profiles (lower(username));
create index if not exists profiles_public_discovery_idx
  on public.profiles (lower(username))
  where profile_visibility = 'public' and discoverable = true;

grant select, insert, update on public.profiles to service_role;

create or replace function public.set_profile_updated_at()
returns trigger language plpgsql set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_profile_updated_at();

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_display_name text;
begin
  v_display_name := coalesce(nullif(btrim(new.raw_user_meta_data ->> 'display_name'), ''), 'Creator');
  insert into public.profiles (id, display_name, username)
  values (new.id, v_display_name, 'creator_' || substr(replace(new.id::text, '-', ''), 1, 8))
  on conflict (id) do nothing;
  return new;
end;
$$;

-- Enforce recipient privacy on the server even when a client guesses a UUID.
create or replace function public.create_direct_conversation(
    p_actor_user_id uuid,
    p_recipient_user_id uuid
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_first text;
    v_second text;
    v_pair_key text;
    v_conversation_id uuid;
    v_allow_messages boolean;
begin
    if p_actor_user_id is null or p_recipient_user_id is null
       or p_actor_user_id = p_recipient_user_id then
        raise exception 'invalid direct conversation participants'
          using errcode = '22023';
    end if;

    select allow_direct_messages into v_allow_messages
      from public.profiles where id = p_recipient_user_id;
    if coalesce(v_allow_messages, false) is not true then
        raise exception 'recipient does not accept direct messages'
          using errcode = '42501';
    end if;

    v_first := least(p_actor_user_id::text, p_recipient_user_id::text);
    v_second := greatest(p_actor_user_id::text, p_recipient_user_id::text);
    v_pair_key := v_first || ':' || v_second;

    insert into public.direct_conversations(pair_key)
    values (v_pair_key)
    on conflict (pair_key) do nothing;

    select id into v_conversation_id
      from public.direct_conversations where pair_key = v_pair_key;

    insert into public.direct_conversation_participants(conversation_id, user_id)
    values (v_conversation_id, p_actor_user_id), (v_conversation_id, p_recipient_user_id)
    on conflict (conversation_id, user_id) do nothing;

    return v_conversation_id;
end;
$$;

revoke all on function public.create_direct_conversation(uuid, uuid) from public, anon, authenticated;
grant execute on function public.create_direct_conversation(uuid, uuid) to service_role;
