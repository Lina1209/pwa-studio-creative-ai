-- Private one-to-one direct messaging, deliberately separate from support tickets.
-- All reads and writes are mediated by the authenticated backend using service_role.
create table if not exists public.direct_conversations (
    id uuid primary key default gen_random_uuid(),
    pair_key text not null unique,
    created_at timestamptz not null default now(),
    last_message_at timestamptz not null default now(),
    constraint direct_conversations_pair_key_format
      check (pair_key ~ '^[0-9a-f-]{36}:[0-9a-f-]{36}$')
);

create table if not exists public.direct_conversation_participants (
    conversation_id uuid not null references public.direct_conversations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    joined_at timestamptz not null default now(),
    last_read_at timestamptz,
    primary key (conversation_id, user_id)
);

create index if not exists direct_conversation_participants_user_idx
    on public.direct_conversation_participants(user_id, joined_at desc);

create table if not exists public.direct_messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null,
    sender_user_id uuid not null,
    body text not null,
    idempotency_key uuid not null,
    created_at timestamptz not null default now(),
    constraint direct_messages_body_length
      check (char_length(btrim(body)) between 1 and 5000),
    constraint direct_messages_participant_fk
      foreign key (conversation_id, sender_user_id)
      references public.direct_conversation_participants(conversation_id, user_id)
      on delete cascade,
    constraint direct_messages_sender_idempotency_unique
      unique (sender_user_id, idempotency_key)
);

create index if not exists direct_messages_conversation_created_idx
    on public.direct_messages(conversation_id, created_at desc, id desc);

alter table public.direct_conversations enable row level security;
alter table public.direct_conversation_participants enable row level security;
alter table public.direct_messages enable row level security;

revoke all on public.direct_conversations from public, anon, authenticated;
revoke all on public.direct_conversation_participants from public, anon, authenticated;
revoke all on public.direct_messages from public, anon, authenticated;
grant select, insert, update, delete on public.direct_conversations to service_role;
grant select, insert, update, delete on public.direct_conversation_participants to service_role;
grant select, insert, update, delete on public.direct_messages to service_role;

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
begin
    if p_actor_user_id is null or p_recipient_user_id is null
       or p_actor_user_id = p_recipient_user_id then
        raise exception 'invalid direct conversation participants'
          using errcode = '22023';
    end if;

    v_first := least(p_actor_user_id::text, p_recipient_user_id::text);
    v_second := greatest(p_actor_user_id::text, p_recipient_user_id::text);
    v_pair_key := v_first || ':' || v_second;

    insert into public.direct_conversations(pair_key)
    values (v_pair_key)
    on conflict (pair_key) do nothing;

    select id into v_conversation_id
      from public.direct_conversations
     where pair_key = v_pair_key;

    insert into public.direct_conversation_participants(conversation_id, user_id)
    values (v_conversation_id, p_actor_user_id), (v_conversation_id, p_recipient_user_id)
    on conflict (conversation_id, user_id) do nothing;

    return v_conversation_id;
end;
$$;

create or replace function public.send_direct_message(
    p_conversation_id uuid,
    p_sender_user_id uuid,
    p_body text,
    p_idempotency_key uuid
)
returns table(message_id uuid, conversation_id uuid, sender_user_id uuid,
              body text, created_at timestamptz, replayed boolean)
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_message public.direct_messages%rowtype;
    v_replayed boolean := false;
    v_body text := btrim(coalesce(p_body, ''));
begin
    if p_conversation_id is null or p_sender_user_id is null
       or p_idempotency_key is null
       or char_length(v_body) < 1 or char_length(v_body) > 5000 then
        raise exception 'invalid direct message payload'
          using errcode = '22023';
    end if;

    if not exists (
        select 1 from public.direct_conversation_participants as participant
         where participant.conversation_id = p_conversation_id
           and participant.user_id = p_sender_user_id
    ) then
        raise exception 'sender is not a conversation participant'
          using errcode = '42501';
    end if;

    insert into public.direct_messages(
        conversation_id, sender_user_id, body, idempotency_key
    ) values (
        p_conversation_id, p_sender_user_id, v_body, p_idempotency_key
    )
    on conflict on constraint direct_messages_sender_idempotency_unique do nothing
    returning * into v_message;

    if not found then
        v_replayed := true;
        select * into v_message
          from public.direct_messages as existing_message
         where existing_message.sender_user_id = p_sender_user_id
           and existing_message.idempotency_key = p_idempotency_key;
        if v_message.conversation_id <> p_conversation_id
           or v_message.body <> v_body then
            raise exception 'idempotency key was already used for another message'
              using errcode = '23505';
        end if;
    else
        update public.direct_conversations as conversation
           set last_message_at = v_message.created_at
         where conversation.id = p_conversation_id;
    end if;

    return query select v_message.id, v_message.conversation_id,
        v_message.sender_user_id, v_message.body, v_message.created_at, v_replayed;
end;
$$;

revoke all on function public.create_direct_conversation(uuid, uuid) from public, anon, authenticated;
revoke all on function public.send_direct_message(uuid, uuid, text, uuid) from public, anon, authenticated;
grant execute on function public.create_direct_conversation(uuid, uuid) to service_role;
grant execute on function public.send_direct_message(uuid, uuid, text, uuid) to service_role;
