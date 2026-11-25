-- Assistant history integrity: browser clients may create only user messages.
-- Assistant-role rows are written by the trusted backend using the server-only service key.
alter table public.assistant_messages enable row level security;

drop policy if exists "Users manage own assistant messages" on public.assistant_messages;
drop policy if exists "Users read own assistant messages" on public.assistant_messages;
drop policy if exists "Users insert own user messages" on public.assistant_messages;
drop policy if exists "Users delete own assistant messages" on public.assistant_messages;

revoke all on public.assistant_messages from anon;
revoke update on public.assistant_messages from authenticated;
grant select, insert, delete on public.assistant_messages to authenticated;
grant select, insert on public.assistant_messages to service_role;

create policy "Users read own assistant messages" on public.assistant_messages
  for select to authenticated
  using (
    auth.uid() = user_id
    and exists (
      select 1 from public.assistant_conversations c
      where c.id = conversation_id and c.user_id = auth.uid()
    )
  );

create policy "Users insert own user messages" on public.assistant_messages
  for insert to authenticated
  with check (
    auth.uid() = user_id
    and role = 'user'
    and exists (
      select 1 from public.assistant_conversations c
      where c.id = conversation_id and c.user_id = auth.uid()
    )
  );

create policy "Users delete own assistant messages" on public.assistant_messages
  for delete to authenticated
  using (
    auth.uid() = user_id
    and exists (
      select 1 from public.assistant_conversations c
      where c.id = conversation_id and c.user_id = auth.uid()
    )
  );
