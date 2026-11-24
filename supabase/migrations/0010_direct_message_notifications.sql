-- Permit the notification type already emitted by the direct-message endpoint.
-- Existing notifications remain unchanged.
alter table public.user_notifications
  drop constraint if exists user_notifications_type_check;

alter table public.user_notifications
  add constraint user_notifications_type_check
  check (type in ('report_update', 'account_notice', 'system', 'direct_message'));
