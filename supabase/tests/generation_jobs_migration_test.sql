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
as $$ select string_to_array(trim(both '/' from object_name), '/') [1:greatest(array_length(string_to_array(trim(both '/' from object_name), '/'), 1) - 1, 0)] $$;

\ir ../migrations/0005_cloud_projects_and_storage.sql
\ir ../migrations/0007_enforce_project_owner_integrity.sql
\ir ../migrations/0009_generation_jobs_and_outbox.sql

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
do $$
declare visible_count integer;
begin
  select count(*) into visible_count from public.generation_jobs;
  if visible_count <> 1 then
    raise exception 'RLS leak or missing own job: expected 1 row, saw %', visible_count;
  end if;

  begin
    insert into public.generation_jobs(
      user_id, job_type, provider, model, idempotency_key, request_hash
    ) values (
      auth.uid(), 'ai_processing', 'test-provider', 'test-model',
      'client-write-key', repeat('d', 64)
    );
    raise exception 'Authenticated client unexpectedly inserted a generation job';
  exception when insufficient_privilege then
    null;
  end;

  begin
    insert into public.outbox_events(aggregate_type, aggregate_id, event_type)
    values ('generation_job', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'generation_job.created');
    raise exception 'Authenticated client unexpectedly inserted an outbox event';
  exception when insufficient_privilege then
    null;
  end;
end;
$$;
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
