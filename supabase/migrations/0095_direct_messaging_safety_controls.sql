-- Abuse-prevention foundation for private direct messaging.
-- A block is directional: the blocked account cannot send to the blocker.
create table if not exists public.direct_user_blocks (
  blocker_user_id uuid not null references auth.users(id) on delete cascade,
  blocked_user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker_user_id, blocked_user_id),
  constraint direct_user_blocks_no_self check (blocker_user_id <> blocked_user_id)
);
create index if not exists direct_user_blocks_blocked_idx
  on public.direct_user_blocks(blocked_user_id, blocker_user_id);

create table if not exists public.direct_message_reports (
  id uuid primary key default gen_random_uuid(),
  reporter_user_id uuid not null references auth.users(id) on delete cascade,
  target_user_id uuid not null references auth.users(id) on delete cascade,
  message_id uuid references public.direct_messages(id) on delete set null,
  category text not null check (category in ('spam','harassment','scam','threats','inappropriate','other')),
  details text not null default '' check (char_length(details) <= 2000),
  status text not null default 'open' check (status in ('open','reviewing','resolved','dismissed')),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by uuid references auth.users(id) on delete set null,
  constraint direct_message_reports_no_self check (reporter_user_id <> target_user_id)
);
create index if not exists direct_message_reports_queue_idx
  on public.direct_message_reports(status, created_at desc);

alter table public.direct_user_blocks enable row level security;
alter table public.direct_message_reports enable row level security;
revoke all on public.direct_user_blocks from public, anon, authenticated;
revoke all on public.direct_message_reports from public, anon, authenticated;
grant select, insert, delete on public.direct_user_blocks to service_role;
grant select, insert, update on public.direct_message_reports to service_role;

create or replace function public.set_direct_user_block(
  p_blocker_user_id uuid, p_blocked_user_id uuid, p_blocked boolean
) returns boolean
language plpgsql security definer set search_path = ''
as $$
begin
  if p_blocker_user_id is null or p_blocked_user_id is null
     or p_blocker_user_id = p_blocked_user_id or p_blocked is null
     or not exists (select 1 from auth.users u where u.id = p_blocked_user_id) then
    raise exception 'invalid block participants' using errcode = '22023';
  end if;
  if p_blocked then
    insert into public.direct_user_blocks(blocker_user_id, blocked_user_id)
    values (p_blocker_user_id, p_blocked_user_id)
    on conflict (blocker_user_id, blocked_user_id) do nothing;
  else
    delete from public.direct_user_blocks
    where blocker_user_id = p_blocker_user_id and blocked_user_id = p_blocked_user_id;
  end if;
  return true;
end;
$$;

create or replace function public.report_direct_message(
  p_reporter_user_id uuid, p_target_user_id uuid, p_message_id uuid,
  p_category text, p_details text default ''
) returns uuid
language plpgsql security definer set search_path = ''
as $$
declare v_report_id uuid; v_conversation_id uuid;
begin
  if p_reporter_user_id is null or p_target_user_id is null
     or p_reporter_user_id = p_target_user_id
     or p_category not in ('spam','harassment','scam','threats','inappropriate','other')
     or char_length(coalesce(p_details,'')) > 2000 then
    raise exception 'invalid direct message report' using errcode = '22023';
  end if;
  if not exists (select 1 from auth.users u where u.id = p_target_user_id) then
    raise exception 'reported user not found' using errcode = '23503';
  end if;
  if p_message_id is not null then
    select m.conversation_id into v_conversation_id
    from public.direct_messages m
    where m.id = p_message_id and m.sender_user_id = p_target_user_id;
    if v_conversation_id is null or not exists (
      select 1 from public.direct_conversation_participants p
      where p.conversation_id = v_conversation_id and p.user_id = p_reporter_user_id
    ) then
      raise exception 'reported message is not in reporter conversation'
        using errcode = '42501';
    end if;
  end if;
  insert into public.direct_message_reports(
    reporter_user_id,target_user_id,message_id,category,details
  ) values (
    p_reporter_user_id,p_target_user_id,p_message_id,p_category,btrim(coalesce(p_details,''))
  ) returning id into v_report_id;
  return v_report_id;
end;
$$;

create or replace function public.enforce_direct_message_safety()
returns trigger language plpgsql security definer set search_path = ''
as $$
declare v_peer uuid; v_recent integer;
begin
  select p.user_id into v_peer
  from public.direct_conversation_participants p
  where p.conversation_id = new.conversation_id
    and p.user_id <> new.sender_user_id
  limit 1;
  if v_peer is null then
    raise exception 'conversation recipient not found' using errcode = '42501';
  end if;
  if exists (
    select 1 from public.direct_user_blocks b
    where b.blocker_user_id = v_peer and b.blocked_user_id = new.sender_user_id
  ) then
    raise exception 'recipient does not accept messages from this account'
      using errcode = '42501';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(
    new.sender_user_id::text || ':' || new.conversation_id::text, 0
  ));
  select count(*) into v_recent from public.direct_messages m
  where m.sender_user_id = new.sender_user_id
    and m.conversation_id = new.conversation_id
    and m.created_at > now() - interval '1 minute';
  if v_recent >= 20 then
    raise exception 'direct message rate limit exceeded' using errcode = 'P0001';
  end if;
  return new;
end;
$$;
drop trigger if exists direct_messages_safety_guard on public.direct_messages;
create trigger direct_messages_safety_guard
before insert on public.direct_messages
for each row execute function public.enforce_direct_message_safety();

revoke all on function public.set_direct_user_block(uuid,uuid,boolean) from public, anon, authenticated;
revoke all on function public.report_direct_message(uuid,uuid,uuid,text,text) from public, anon, authenticated;
grant execute on function public.set_direct_user_block(uuid,uuid,boolean) to service_role;
grant execute on function public.report_direct_message(uuid,uuid,uuid,text,text) to service_role;
