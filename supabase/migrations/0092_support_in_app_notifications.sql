-- Durable, private in-app notifications for support activity.
-- Apply after 0091_support_inbox_atomic_mutations_and_categories.sql.
create table if not exists public.support_notifications (
  id uuid primary key default gen_random_uuid(),
  recipient_user_id uuid not null references auth.users(id) on delete cascade,
  actor_user_id uuid references auth.users(id) on delete set null,
  ticket_id uuid references public.support_tickets(id) on delete cascade,
  kind text not null check (kind in ('support_ticket_new','support_ticket_reply')),
  title text not null check (char_length(title) between 1 and 120),
  body text not null check (char_length(body) between 1 and 300),
  dedupe_key text not null unique check (char_length(dedupe_key) between 1 and 180),
  created_at timestamptz not null default now(),
  read_at timestamptz
);
create index if not exists support_notifications_recipient_unread_idx
  on public.support_notifications(recipient_user_id, created_at desc) where read_at is null;
create index if not exists support_notifications_recipient_created_idx
  on public.support_notifications(recipient_user_id, created_at desc);
alter table public.support_notifications enable row level security;
revoke all on public.support_notifications from public, anon, authenticated;
grant select, insert, update on public.support_notifications to service_role;

create or replace function public.create_support_notification(
  p_recipient_user_id uuid, p_actor_user_id uuid, p_ticket_id uuid,
  p_kind text, p_title text, p_body text, p_dedupe_key text
) returns uuid language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_id uuid;
begin
  if p_recipient_user_id is null
     or p_kind not in ('support_ticket_new','support_ticket_reply')
     or p_title is null or char_length(btrim(p_title)) not between 1 and 120
     or p_body is null or char_length(btrim(p_body)) not between 1 and 300
     or p_dedupe_key is null or char_length(p_dedupe_key) not between 1 and 180 then
    raise exception 'invalid support notification' using errcode = '22023';
  end if;
  insert into public.support_notifications(recipient_user_id,actor_user_id,ticket_id,kind,title,body,dedupe_key)
  values (p_recipient_user_id,p_actor_user_id,p_ticket_id,p_kind,btrim(p_title),btrim(p_body),p_dedupe_key)
  on conflict (dedupe_key) do nothing returning id into v_id;
  if v_id is null then select id into v_id from public.support_notifications where dedupe_key=p_dedupe_key; end if;
  return v_id;
end; $$;
revoke all on function public.create_support_notification(uuid,uuid,uuid,text,text,text,text) from public, anon, authenticated;
grant execute on function public.create_support_notification(uuid,uuid,uuid,text,text,text,text) to service_role;
comment on table public.support_notifications is 'Private per-recipient in-app notifications for support events. Backend-only access.';
