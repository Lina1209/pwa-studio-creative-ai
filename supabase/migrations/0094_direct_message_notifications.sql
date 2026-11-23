-- Private in-app notifications for direct messages; support stays separate.
create table if not exists public.user_notifications (
 id uuid primary key default gen_random_uuid(),
 recipient_user_id uuid not null references auth.users(id) on delete cascade,
 actor_user_id uuid references auth.users(id) on delete set null,
 conversation_id uuid references public.direct_conversations(id) on delete cascade,
 message_id uuid references public.direct_messages(id) on delete cascade,
 kind text not null check (kind in ('direct_message_new')),
 title text not null check (char_length(title) between 1 and 120),
 body text not null check (char_length(body) between 1 and 300),
 dedupe_key text not null unique check (char_length(dedupe_key) between 1 and 180),
 created_at timestamptz not null default now(),
 read_at timestamptz,
 constraint user_notifications_dm_refs check (
   conversation_id is not null and message_id is not null and actor_user_id is not null
 )
);
create index if not exists user_notifications_recipient_unread_idx
 on public.user_notifications(recipient_user_id, created_at desc) where read_at is null;
create index if not exists user_notifications_recipient_created_idx
 on public.user_notifications(recipient_user_id, created_at desc);
alter table public.user_notifications enable row level security;
revoke all on public.user_notifications from public, anon, authenticated;
grant select, insert, update on public.user_notifications to service_role;

create or replace function public.create_direct_message_notification(
 p_conversation_id uuid, p_message_id uuid, p_actor_user_id uuid,
 p_title text, p_body text, p_dedupe_key text
) returns uuid language plpgsql security definer set search_path = ''
as $$
declare v_recipient uuid; v_id uuid;
begin
 if p_conversation_id is null or p_message_id is null or p_actor_user_id is null
    or p_title is null or char_length(btrim(p_title)) not between 1 and 120
    or p_body is null or char_length(btrim(p_body)) not between 1 and 300
    or p_dedupe_key is null or char_length(p_dedupe_key) not between 1 and 180 then
   raise exception 'invalid direct message notification' using errcode = '22023';
 end if;
 if not exists (
   select 1 from public.direct_messages m
   where m.id = p_message_id and m.conversation_id = p_conversation_id
     and m.sender_user_id = p_actor_user_id
 ) then raise exception 'message does not match sender and conversation' using errcode = '42501'; end if;
 select p.user_id into v_recipient from public.direct_conversation_participants p
 where p.conversation_id = p_conversation_id and p.user_id <> p_actor_user_id limit 1;
 if v_recipient is null then raise exception 'conversation recipient not found' using errcode = '23503'; end if;
 insert into public.user_notifications(recipient_user_id,actor_user_id,conversation_id,message_id,kind,title,body,dedupe_key)
 values (v_recipient,p_actor_user_id,p_conversation_id,p_message_id,'direct_message_new',
         btrim(p_title),btrim(p_body),p_dedupe_key)
 on conflict (dedupe_key) do nothing returning id into v_id;
 if v_id is null then
   select n.id into v_id from public.user_notifications n where n.dedupe_key=p_dedupe_key;
 end if;
 return v_id;
end;
$$;
revoke all on function public.create_direct_message_notification(uuid,uuid,uuid,text,text,text)
 from public, anon, authenticated;
grant execute on function public.create_direct_message_notification(uuid,uuid,uuid,text,text,text)
 to service_role;
