-- Disposable PostgreSQL integration test for migrations 0005, 0007 and 0009.
-- Run with psql -v ON_ERROR_STOP=1 -f this_file against an empty test database.
\set ON_ERROR_STOP on

create extension if not exists pgcrypto;
create schema if not exists auth;
create schema if not exists storage;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end;
$$;

create table auth.users (
  id uuid primary key
);

create or replace function auth.uid()
returns uuid
language sql stable
as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
grant usage on schema auth to authenticated, service_role;
grant execute on function auth.uid() to authenticated, service_role;

create table storage.buckets (
  id text primary key,
  name text not null,
  public boolean not null default false,
  file_size_limit bigint,
  allowed_mime_types text[]
);

create table storage.objects (
  id bigint generated always as identity primary key,
  bucket_id text not null references storage.buckets(id),
  name text not null
);

create or replace function storage.foldername(object_name text)
returns text[]
language sql immutable
as $$
  select case
    when position('/' in trim(both '/' from object_name)) = 0 then array[]::text[]
    else (string_to_array(trim(both '/' from object_name), '/'))[1:array_length(string_to_array(trim(both '/' from object_name), '/'), 1) - 1]
  end
$$;

\ir ../migrations/0005_cloud_projects_and_storage.sql
\ir ../migrations/0007_enforce_project_owner_integrity.sql
\ir ../migrations/0009_generation_jobs_and_outbox.sql
\ir ../migrations/0010_create_generation_job_rpc.sql

insert into auth.users(id) values
  ('11111111-1111-4111-8111-111111111111'),
  ('22222222-2222-4222-8222-222222222222');

insert into public.projects(id, owner_id, title)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', '11111111-1111-4111-8111-111111111111', 'Test project');

insert into public.generation_jobs(
  id, user_id, project_id, job_type, provider, model, idempotency_key, request_hash
) values
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '11111111-1111-4111-8111-111111111111',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'video_generation', 'test-provider', 'test-model',
   'test-key-user-one', repeat('a', 64)),
  ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', '22222222-2222-4222-8222-222222222222',
   null, 'image_generation', 'test-provider', 'test-model',
   'test-key-user-two', repeat('b', 64));

insert into public.outbox_events(aggregate_type, aggregate_id, event_type, payload)
values ('generation_job', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        'generation_job.created', '{"test": true}'::jsonb);


-- Only the trusted backend service role may execute the RPC.
do $$
begin
  if has_function_privilege(
    'authenticated',
    'public.create_generation_job_with_outbox(uuid,uuid,text,text,text,text,text,jsonb,jsonb)',
    'EXECUTE'
  ) then
    raise exception 'Authenticated role unexpectedly has execute permission on the job creation RPC';
  end if;
  if not has_function_privilege(
    'service_role',
    'public.create_generation_job_with_outbox(uuid,uuid,text,text,text,text,text,jsonb,jsonb)',
    'EXECUTE'
  ) then
    raise exception 'Trusted service_role is missing execute permission on the job creation RPC';
  end if;
end;
$$;

-- The backend-only RPC creates one job and one outbox event atomically.
do $
declare
  v_first record;
  v_second record;
  v_event_count integer;
begin
  select * into v_first
  from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111',
    null,
    'ai_processing',
    'test-provider',
    'test-model',
    'rpc-idempotency-key-1',
    repeat('e', 64),
    '{"prompt":"test"}'::jsonb,
    '{"version":1}'::jsonb
  );

  select * into v_second
  from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111',
    null,
    'ai_processing',
    'test-provider',
    'test-model',
    'rpc-idempotency-key-1',
    repeat('e', 64),
    '{"prompt":"test"}'::jsonb,
    '{"version":1}'::jsonb
  );

  if not v_first.created or v_second.created
     or v_first.job_id <> v_second.job_id
     or v_first.event_id is distinct from v_second.event_id then
    raise exception 'Idempotent replay did not return the original job and event';
  end if;

  select count(*) into v_event_count
  from public.outbox_events
  where aggregate_id = v_first.job_id
    and event_type = 'generation_job.created';
  if v_event_count <> 1 then
    raise exception 'Expected exactly one creation outbox event, found %', v_event_count;
  end if;

  begin
    perform public.create_generation_job_with_outbox(
      '11111111-1111-4111-8111-111111111111',
      null,
      'ai_processing',
      'test-provider',
      'test-model',
      'rpc-idempotency-key-1',
      repeat('f', 64),
      '{"prompt":"different"}'::jsonb,
      '{"version":1}'::jsonb
    );
    raise exception 'Reusing an idempotency key with a different request was accepted';
  exception when sqlstate '22023' then
    null;
  end;
end;
$;

-- A job must not reference another user's project.
do $$
begin
  begin
    insert into public.generation_jobs(
      user_id, project_id, job_type, provider, model, idempotency_key, request_hash
    ) values (
      '22222222-2222-4222-8222-222222222222',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      'video_generation', 'test-provider', 'test-model',
      'cross-owner-key', repeat('c', 64)
    );
    raise exception 'Expected cross-owner project reference to be rejected';
  exception when foreign_key_violation then
    null;
  end;
end;
$$;

-- Authenticated users can read only their own jobs, and cannot write jobs/outbox.
set request.jwt.claim.sub = '11111111-1111-4111-8111-111111111111';
set role authenticated;
select 1 / case when count(*) = 1 then 1 else 0 end as assert_only_own_job_visible
from public.generation_jobs;
select 1 / case when not has_table_privilege('authenticated', 'public.generation_jobs', 'INSERT') then 1 else 0 end
  as assert_clients_cannot_insert_jobs;
select 1 / case when not has_table_privilege('authenticated', 'public.outbox_events', 'INSERT') then 1 else 0 end
  as assert_clients_cannot_insert_outbox;
reset role;
reset request.jwt.claim.sub;

-- Deleting a project must preserve the job while detaching the optional project link.
delete from public.projects where id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
do $$
begin
  if not exists (
    select 1 from public.generation_jobs
    where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' and project_id is null
  ) then
    raise exception 'Deleting a project did not preserve its generation job with project_id=NULL';
  end if;
end;
$$;

select 'generation jobs migration integration checks passed' as result;
