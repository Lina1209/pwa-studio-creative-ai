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

\i supabase/migrations/0055_private_support_inbox.sql
\i supabase/migrations/0091_support_inbox_atomic_mutations_and_categories.sql

insert into auth.users(id) values
  ('11111111-1111-4111-8111-111111111111'),
  ('22222222-2222-4222-8222-222222222222')
on conflict do nothing;

do $support_inbox_test$
declare
  v_user uuid := '11111111-1111-4111-8111-111111111111';
  v_admin uuid := '22222222-2222-4222-8222-222222222222';
  v_ticket uuid;
  v_count integer;
  v_status text;
  v_first_response timestamptz;
  v_rejected boolean := false;
begin
  if has_function_privilege('authenticated',
      'public.create_support_ticket_with_message(uuid,text,text,text,jsonb)', 'EXECUTE') then
    raise exception 'authenticated role must not execute support ticket RPC';
  end if;
  if not has_function_privilege('service_role',
      'public.create_support_ticket_with_message(uuid,text,text,text,jsonb)', 'EXECUTE') then
    raise exception 'service_role must execute support ticket RPC';
  end if;
  if has_table_privilege('authenticated', 'public.support_tickets', 'SELECT') then
    raise exception 'authenticated role must not read support tickets directly';
  end if;

  select id into v_ticket
    from public.create_support_ticket_with_message(
      v_user, 'Save issue', 'The project did not save.', 'bug',
      '{"page_path":"#movie"}'::jsonb
    );
  if v_ticket is null then raise exception 'ticket was not created'; end if;

  select count(*) into v_count
    from public.support_ticket_messages
   where ticket_id = v_ticket;
  if v_count <> 1 then raise exception 'ticket and initial message were not created atomically'; end if;

  perform public.add_support_ticket_message(v_ticket, v_user, 'user', 'Additional details');
  select status into v_status from public.support_tickets where id = v_ticket;
  if v_status <> 'open' then raise exception 'user reply must return ticket to open queue'; end if;

  perform public.add_support_ticket_message(v_ticket, v_admin, 'admin', 'We are investigating');
  select status, first_response_at into v_status, v_first_response
    from public.support_tickets where id = v_ticket;
  if v_status <> 'waiting_user' then raise exception 'admin reply must wait for user'; end if;
  if v_first_response is null then raise exception 'first response timestamp was not recorded'; end if;

  update public.support_tickets set status = 'closed' where id = v_ticket;
  begin
    perform public.add_support_ticket_message(v_ticket, v_user, 'user', 'This must be rejected');
  exception when object_not_in_prerequisite_state then
    v_rejected := true;
  end;
  if not v_rejected then raise exception 'user reply to closed ticket was accepted'; end if;

  v_rejected := false;
  begin
    perform * from public.create_support_ticket_with_message(
      v_user, 'Invalid category', 'No', 'root', '{}'::jsonb
    );
  exception when invalid_parameter_value then
    v_rejected := true;
  end;
  if not v_rejected then raise exception 'unknown support category was accepted'; end if;
end;
$support_inbox_test$;
