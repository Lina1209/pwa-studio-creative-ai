-- Private support inbox. All reads/writes go through the authenticated API using service_role.
create table if not exists public.support_tickets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  subject text not null check (char_length(subject) between 3 and 160),
  status text not null default 'open' check (status in ('open','in_progress','waiting_user','resolved','closed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_message_at timestamptz not null default now()
);
create index if not exists support_tickets_user_updated_idx on public.support_tickets(user_id, updated_at desc);
create index if not exists support_tickets_admin_queue_idx on public.support_tickets(status, last_message_at desc);
alter table public.support_tickets enable row level security;
revoke all on public.support_tickets from public, anon, authenticated;
grant select, insert, update on public.support_tickets to service_role;

create table if not exists public.support_ticket_messages (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references public.support_tickets(id) on delete cascade,
  sender_user_id uuid not null references auth.users(id) on delete restrict,
  sender_role text not null check (sender_role in ('user','admin')),
  body text not null check (char_length(body) between 1 and 5000),
  created_at timestamptz not null default now()
);
create index if not exists support_ticket_messages_ticket_created_idx
  on public.support_ticket_messages(ticket_id, created_at asc);
alter table public.support_ticket_messages enable row level security;
revoke all on public.support_ticket_messages from public, anon, authenticated;
grant select, insert on public.support_ticket_messages to service_role;

comment on table public.support_tickets is 'Private support inbox; API enforces owner/admin access and writes audit events.';
comment on table public.support_ticket_messages is 'Private support conversation messages; API enforces ticket access.';
