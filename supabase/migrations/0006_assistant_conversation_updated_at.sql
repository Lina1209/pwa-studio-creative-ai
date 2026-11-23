-- PWA Studio: keep assistant conversation ordering accurate after renames.
-- Apply after 0004_assistant_chat_history.sql.
-- This migration changes only the updated_at behavior of existing conversations.

create or replace function public.set_assistant_conversation_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists assistant_conversation_updated_at on public.assistant_conversations;
create trigger assistant_conversation_updated_at
  before update on public.assistant_conversations
  for each row execute function public.set_assistant_conversation_updated_at();
