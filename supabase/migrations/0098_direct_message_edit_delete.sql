-- Safe message editing and soft deletion for private conversations.
begin;

alter table public.direct_messages
  add column if not exists edited_at timestamptz,
  add column if not exists deleted_at timestamptz;

create or replace function public.edit_direct_message(
  p_conversation_id uuid,
  p_message_id uuid,
  p_sender_user_id uuid,
  p_body text
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_body text := btrim(coalesce(p_body, ''));
begin
  if p_conversation_id is null or p_message_id is null or p_sender_user_id is null
     or char_length(v_body) < 1 or char_length(v_body) > 5000 then
    raise exception 'invalid direct message edit payload' using errcode = '22023';
  end if;

  update public.direct_messages
     set body = v_body, edited_at = now()
   where id = p_message_id
     and conversation_id = p_conversation_id
     and sender_user_id = p_sender_user_id
     and deleted_at is null
     and created_at > now() - interval '15 minutes';

  if not found then
    return false;
  end if;
  return true;
end;
$$;

create or replace function public.delete_direct_message(
  p_conversation_id uuid,
  p_message_id uuid,
  p_sender_user_id uuid
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_conversation_id is null or p_message_id is null or p_sender_user_id is null then
    raise exception 'invalid direct message delete payload' using errcode = '22023';
  end if;

  update public.direct_messages
     set body = '', deleted_at = now(), edited_at = null
   where id = p_message_id
     and conversation_id = p_conversation_id
     and sender_user_id = p_sender_user_id
     and deleted_at is null;

  if not found then
    return false;
  end if;
  return true;
end;
$$;

revoke all on function public.edit_direct_message(uuid,uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.delete_direct_message(uuid,uuid,uuid) from public, anon, authenticated;
grant execute on function public.edit_direct_message(uuid,uuid,uuid,text) to service_role;
grant execute on function public.delete_direct_message(uuid,uuid,uuid) to service_role;

commit;
