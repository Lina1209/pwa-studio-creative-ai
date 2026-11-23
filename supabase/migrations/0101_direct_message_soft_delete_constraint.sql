-- Permit body redaction only for messages that have been soft-deleted.
-- The original body-length invariant remains in force for every live message.
alter table public.direct_messages
  drop constraint if exists direct_messages_body_length;

alter table public.direct_messages
  add constraint direct_messages_body_length
  check (
    (deleted_at is null and char_length(btrim(body)) between 1 and 5000)
    or (deleted_at is not null and body = '')
  );

comment on constraint direct_messages_body_length on public.direct_messages is
  'Live messages must contain 1-5000 non-whitespace characters; soft-deleted messages must have their body redacted to an empty string.';
