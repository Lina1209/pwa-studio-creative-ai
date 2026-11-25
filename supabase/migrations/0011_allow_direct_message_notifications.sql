-- Allow private-message notifications in addition to moderation and system notices.
alter table public.user_notifications
  drop constraint if exists user_notifications_type_check;

alter table public.user_notifications
  add constraint user_notifications_type_check
  check (type in ('report_update', 'account_notice', 'system', 'direct_message'));
