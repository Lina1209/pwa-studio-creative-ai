-- PWA Studio: private one-to-one conversations and messages.
-- All writes are server-managed; authenticated clients may read only threads they belong to.

create table if not exists public.conversation_threads (
  id uuid primary key default gen_random_uuid(),
  user_a_id uuid not null references auth.users(id) on delete cascade,
  user_b_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_message_at timestamptz,
  constraint conversation_distinct_users check (user_a_id <> user_b_id),
  constraint conversation_canonical_order check (user_a_id < user_b_id),
  constraint conversation_unique_pair unique (user_a_id, user_b_id)
);

create table if not exists public.direct_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.conversation_threads(id) on delete cascade,
  sender_id uuid not null references auth.users(id) on delete cascade,
  recipient_id uuid not null references auth.users(id) on delete cascade,
  body text not null default '' check (char_length(body) <= 8000),
  attachments jsonb not null default '[]'::jsonb
    check (jsonb_typeof(attachments) = 'array' and jsonb_array_length(attachments) <= 10),
  read_at timestamptz,
  edited_at timestamptz,
  deleted_for_sender_at timestamptz,
  deleted_for_recipient_at timestamptz,
  created_at timestamptz not null default now(),
  constraint message_distinct_users check (sender_id <> recipient_id),
  constraint message_content_present check (char_length(trim(body)) > 0 or jsonb_array_length(attachments) > 0)
);

create index if not exists conversation_threads_user_a_idx
  on public.conversation_threads(user_a_id, last_message_at desc nulls last);
create index if not exists conversation_threads_user_b_idx
  on public.conversation_threads(user_b_id, last_message_at desc nulls last);
create index if not exists direct_messages_thread_created_idx
  on public.direct_messages(thread_id, created_at desc);
create index if not exists direct_messages_recipient_unread_idx
  on public.direct_messages(recipient_id, created_at desc) where read_at is null;

alter table public.conversation_threads enable row level security;
alter table public.direct_messages enable row level security;

revoke all on public.conversation_threads from anon, authenticated;
revoke all on public.direct_messages from anon, authenticated;
grant select on public.conversation_threads to authenticated;
grant select on public.direct_messages to authenticated;
grant select, insert, update, delete on public.conversation_threads to service_role;
grant select, insert, update, delete on public.direct_messages to service_role;

drop policy if exists "Participants read own conversations" on public.conversation_threads;
create policy "Participants read own conversations" on public.conversation_threads
  for select to authenticated
  using (auth.uid() = user_a_id or auth.uid() = user_b_id);

drop policy if exists "Participants read own messages" on public.direct_messages;
create policy "Participants read own messages" on public.direct_messages
  for select to authenticated
  using (
    exists (
      select 1 from public.conversation_threads t
      where t.id = thread_id
        and (auth.uid() = t.user_a_id or auth.uid() = t.user_b_id)
    )
  );

comment on table public.conversation_threads is 'Private one-to-one conversation index; writes are server-managed.';
comment on table public.direct_messages is 'Private direct messages; attachment entries contain metadata/storage keys, never public URLs.';
