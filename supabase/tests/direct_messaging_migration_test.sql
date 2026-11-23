\set ON_ERROR_STOP on
create extension if not exists pgcrypto;
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key);
do $roles$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end;
$roles$;

\i supabase/migrations/0093_private_direct_messaging.sql

insert into auth.users(id) values
 ('11111111-1111-4111-8111-111111111111'),
 ('22222222-2222-4222-8222-222222222222'),
 ('33333333-3333-4333-8333-333333333333')
on conflict do nothing;

do $direct_messaging_test$
declare
  v_alice uuid := '11111111-1111-4111-8111-111111111111';
  v_bob uuid := '22222222-2222-4222-8222-222222222222';
  v_eve uuid := '33333333-3333-4333-8333-333333333333';
  v_conversation uuid;
  v_same_conversation uuid;
  v_message uuid;
  v_replay uuid;
  v_count integer;
  v_rejected boolean := false;
begin
  if has_table_privilege('authenticated', 'public.direct_conversations', 'SELECT')
     or has_table_privilege('authenticated', 'public.direct_conversation_participants', 'SELECT')
     or has_table_privilege('authenticated', 'public.direct_messages', 'SELECT') then
    raise exception 'authenticated role must not query direct message tables directly';
  end if;
  if has_function_privilege('authenticated',
      'public.create_direct_conversation(uuid,uuid)', 'EXECUTE')
     or has_function_privilege('authenticated',
      'public.send_direct_message(uuid,uuid,text,uuid)', 'EXECUTE') then
    raise exception 'authenticated role must not execute direct messaging RPCs';
  end if;

  v_conversation := public.create_direct_conversation(v_alice, v_bob);
  v_same_conversation := public.create_direct_conversation(v_bob, v_alice);
  if v_conversation is null or v_conversation <> v_same_conversation then
    raise exception 'one-to-one conversation must be unique regardless of participant order';
  end if;

  select message_id into v_message from public.send_direct_message(
    v_conversation, v_alice, 'Hello Bob', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  );
  select message_id into v_replay from public.send_direct_message(
    v_conversation, v_alice, 'Hello Bob', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  );
  if v_message is null or v_replay <> v_message then
    raise exception 'message retry must be idempotent';
  end if;
  select count(*) into v_count from public.direct_messages
   where conversation_id = v_conversation;
  if v_count <> 1 then raise exception 'duplicate message was persisted'; end if;

  v_rejected := false;
  begin
    perform * from public.send_direct_message(
      v_conversation, v_eve, 'Intrusion attempt',
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    );
  exception when insufficient_privilege then
    v_rejected := true;
  end;
  if not v_rejected then raise exception 'non-participant was allowed to send'; end if;

  v_rejected := false;
  begin
    perform public.create_direct_conversation(v_alice, v_alice);
  exception when invalid_parameter_value then
    v_rejected := true;
  end;
  if not v_rejected then raise exception 'self conversation was accepted'; end if;
end;
$direct_messaging_test$;

\i supabase/migrations/0094_direct_message_notifications.sql
\i supabase/migrations/0095_direct_messaging_safety_controls.sql

do $direct_messaging_safety_test$
declare
  v_alice uuid := '11111111-1111-4111-8111-111111111111';
  v_bob uuid := '22222222-2222-4222-8222-222222222222';
  v_eve uuid := '33333333-3333-4333-8333-333333333333';
  v_conversation uuid;
  v_message uuid;
  v_report uuid;
  v_rejected boolean := false;
begin
  if has_table_privilege('authenticated','public.direct_user_blocks','SELECT')
     or has_table_privilege('authenticated','public.direct_message_reports','SELECT')
     or has_function_privilege('authenticated','public.set_direct_user_block(uuid,uuid,boolean)','EXECUTE')
     or has_function_privilege('authenticated','public.report_direct_message(uuid,uuid,uuid,text,text)','EXECUTE') then
    raise exception 'authenticated role must not access private safety records or RPCs';
  end if;
  v_conversation := public.create_direct_conversation(v_alice,v_bob);
  select message_id into v_message from public.send_direct_message(
    v_conversation,v_bob,'Reportable message','cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  );
  v_report := public.report_direct_message(v_alice,v_bob,v_message,'harassment','Please review.');
  if v_report is null then raise exception 'report was not created'; end if;

  perform public.set_direct_user_block(v_alice,v_bob,true);
  v_rejected := false;
  begin
    perform * from public.send_direct_message(
      v_conversation,v_bob,'Blocked attempt','dddddddd-dddd-4ddd-8ddd-dddddddddddd'
    );
  exception when insufficient_privilege then v_rejected := true;
  end;
  if not v_rejected then raise exception 'blocked account was allowed to send'; end if;

  perform public.set_direct_user_block(v_alice,v_bob,false);
  perform * from public.send_direct_message(
    v_conversation,v_bob,'Unblocked message','eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
  );
end;
$direct_messaging_safety_test$;

\i supabase/migrations/0096_direct_messaging_moderation_console.sql

do $direct_moderation_test$
declare
  v_alice uuid := '11111111-1111-4111-8111-111111111111';
  v_bob uuid := '22222222-2222-4222-8222-222222222222';
  v_conversation uuid;
  v_appeal uuid;
  v_rejected boolean := false;
begin
  if has_table_privilege('authenticated','public.direct_moderation_events','SELECT')
     or has_table_privilege('authenticated','public.direct_moderation_appeals','SELECT')
     or has_function_privilege('authenticated','public.apply_direct_user_moderation(uuid,uuid,text,text,timestamptz)','EXECUTE')
     or has_function_privilege('authenticated','public.review_direct_moderation_appeal(uuid,uuid,text,text)','EXECUTE') then
    raise exception 'authenticated role must not access moderation console storage';
  end if;
  perform public.apply_direct_user_moderation(v_bob,v_alice,'mute','Repeated abusive messages',now()+interval '1 day');
  v_conversation := public.create_direct_conversation(v_bob,v_alice);
  begin
    perform * from public.send_direct_message(v_conversation,v_bob,'Muted attempt','ffffffff-ffff-4fff-8fff-ffffffffffff');
  exception when insufficient_privilege then v_rejected := true;
  end;
  if not v_rejected then raise exception 'muted user was allowed to send'; end if;
  v_appeal := public.create_direct_moderation_appeal(v_bob,'I believe this moderation decision was mistaken.');
  if v_appeal is null then raise exception 'appeal was not created'; end if;
  if not public.review_direct_moderation_appeal(v_appeal,v_alice,'accepted','Restriction lifted after review.') then
    raise exception 'appeal decision failed';
  end if;
  perform * from public.send_direct_message(v_conversation,v_bob,'Restriction lifted','abababab-abab-4aba-8aba-abababababab');
end;
$direct_moderation_test$;
