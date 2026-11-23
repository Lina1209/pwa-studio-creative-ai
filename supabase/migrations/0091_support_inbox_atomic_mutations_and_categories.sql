-- Make support ticket creation and replies atomic, and classify incoming requests.
-- This migration depends on 0055_private_support_inbox.sql.

alter table public.support_tickets
  add column if not exists category text not null default 'general',
  add column if not exists context jsonb not null default '{}'::jsonb,
  add column if not exists first_response_at timestamptz,
  add column if not exists resolved_at timestamptz,
  add column if not exists closed_at timestamptz;

alter table public.support_tickets
  drop constraint if exists support_tickets_category_check;
alter table public.support_tickets
  add constraint support_tickets_category_check
  check (category in ('general','bug','account','billing','feature_request','feedback','safety_privacy'));

alter table public.support_tickets
  drop constraint if exists support_tickets_context_check;
alter table public.support_tickets
  add constraint support_tickets_context_check
  check (jsonb_typeof(context) = 'object' and octet_length(context::text) <= 4096);

create index if not exists support_tickets_category_status_idx
  on public.support_tickets(category, status, last_message_at desc);

create or replace function public.create_support_ticket_with_message(
  p_user_id uuid,
  p_subject text,
  p_body text,
  p_category text default 'general',
  p_context jsonb default '{}'::jsonb
)
returns setof public.support_tickets
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_ticket public.support_tickets%rowtype;
  v_context jsonb := coalesce(p_context, '{}'::jsonb);
begin
  if p_user_id is null
     or p_subject is null or char_length(btrim(p_subject)) < 3 or char_length(btrim(p_subject)) > 160
     or p_body is null or char_length(btrim(p_body)) < 1 or char_length(btrim(p_body)) > 5000
     or p_category not in ('general','bug','account','billing','feature_request','feedback','safety_privacy')
     or jsonb_typeof(v_context) <> 'object'
     or octet_length(v_context::text) > 4096 then
    raise exception 'invalid support ticket' using errcode = '22023';
  end if;

  insert into public.support_tickets(user_id, subject, category, context)
  values (p_user_id, btrim(p_subject), p_category, v_context)
  returning * into v_ticket;

  insert into public.support_ticket_messages(ticket_id, sender_user_id, sender_role, body)
  values (v_ticket.id, p_user_id, 'user', btrim(p_body));

  return next v_ticket;
  return;
end;
$$;

create or replace function public.add_support_ticket_message(
  p_ticket_id uuid,
  p_sender_user_id uuid,
  p_sender_role text,
  p_body text
)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_ticket public.support_tickets%rowtype;
  v_now timestamptz := clock_timestamp();
begin
  if p_ticket_id is null or p_sender_user_id is null
     or p_sender_role not in ('user','admin')
     or p_body is null or char_length(btrim(p_body)) < 1 or char_length(btrim(p_body)) > 5000 then
    raise exception 'invalid support message' using errcode = '22023';
  end if;

  select * into v_ticket
    from public.support_tickets
   where id = p_ticket_id
   for update;

  if not found then
    raise exception 'support ticket not found' using errcode = 'P0002';
  end if;

  if p_sender_role = 'user' and v_ticket.status in ('resolved','closed') then
    raise exception 'support ticket is closed' using errcode = '55000';
  end if;

  insert into public.support_ticket_messages(ticket_id, sender_user_id, sender_role, body)
  values (p_ticket_id, p_sender_user_id, p_sender_role, btrim(p_body));

  update public.support_tickets
     set status = case when p_sender_role = 'admin' then 'waiting_user' else 'open' end,
         first_response_at = case
           when p_sender_role = 'admin' then coalesce(first_response_at, v_now)
           else first_response_at
         end,
         last_message_at = v_now,
         updated_at = v_now
   where id = p_ticket_id;
end;
$$;

revoke all on function public.create_support_ticket_with_message(uuid,text,text,text,jsonb)
  from public, anon, authenticated;
revoke all on function public.add_support_ticket_message(uuid,uuid,text,text)
  from public, anon, authenticated;
grant execute on function public.create_support_ticket_with_message(uuid,text,text,text,jsonb)
  to service_role;
grant execute on function public.add_support_ticket_message(uuid,uuid,text,text)
  to service_role;

comment on function public.create_support_ticket_with_message(uuid,text,text,text,jsonb) is
  'Atomically creates a private support ticket and its first user message. Backend-only.';
comment on function public.add_support_ticket_message(uuid,uuid,text,text) is
  'Atomically appends a support message and updates the ticket lifecycle. Backend-only.';
