-- PWA Studio: persistent AI Companion conversations and messages.
-- Apply this migration in the Supabase SQL Editor for the connected project.

create table if not exists public.assistant_conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'Новый диалог',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.assistant_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.assistant_conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null check (char_length(content) between 1 and 12000),
  created_at timestamptz not null default now()
);

create index if not exists assistant_conversations_user_updated_idx
  on public.assistant_conversations(user_id, updated_at desc);
create index if not exists assistant_messages_conversation_created_idx
  on public.assistant_messages(conversation_id, created_at asc);

alter table public.assistant_conversations enable row level security;
alter table public.assistant_messages enable row level security;

-- Explicit table privileges; RLS remains the row-level security boundary.
grant select, insert, update, delete on public.assistant_conversations to authenticated;
grant select, insert, update, delete on public.assistant_messages to authenticated;

drop policy if exists "Users manage own assistant conversations" on public.assistant_conversations;
create policy "Users manage own assistant conversations" on public.assistant_conversations
  for all to authenticated
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "Users manage own assistant messages" on public.assistant_messages;
create policy "Users manage own assistant messages" on public.assistant_messages
  for all to authenticated
  using (
    auth.uid() = user_id
    and exists (
      select 1 from public.assistant_conversations c
      where c.id = conversation_id and c.user_id = auth.uid()
    )
  )
  with check (
    auth.uid() = user_id
    and exists (
      select 1 from public.assistant_conversations c
      where c.id = conversation_id and c.user_id = auth.uid()
    )
  );

create or replace function public.touch_assistant_conversation_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  update public.assistant_conversations
  set updated_at = now()
  where id = new.conversation_id;
  return new;
end;
$$;

drop trigger if exists assistant_message_updates_conversation on public.assistant_messages;
create trigger assistant_message_updates_conversation
  after insert on public.assistant_messages
  for each row execute function public.touch_assistant_conversation_updated_at();
