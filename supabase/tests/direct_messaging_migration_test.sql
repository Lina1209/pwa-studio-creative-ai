\\set ON_ERROR_STOP on
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

\\i supabase/migrations/0093_private_direct_messaging.sql

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
