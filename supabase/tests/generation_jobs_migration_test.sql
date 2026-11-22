-- Disposable PostgreSQL integration test for cloud ownership and generation-job migrations.
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

-- Minimal Mini Movie Studio tables matching the production baseline in 0001.
create table public.studio_projects (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade
);
create table public.studio_scenes (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null references public.studio_projects(id) on delete cascade,
  scene_number integer not null default 1,
  output_path text
);
create table public.studio_media (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid references public.studio_projects(id) on delete set null,
  media_type text not null,
  storage_path text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

\ir ../migrations/0011_link_generation_jobs_to_movie_scenes.sql
\ir ../migrations/0012_create_scene_generation_job_rpc.sql
\ir ../migrations/0013_generation_job_worker_lifecycle.sql
\ir ../migrations/0014_outbox_delivery_lifecycle.sql

insert into auth.users(id) values
  ('11111111-1111-4111-8111-111111111111'),
  ('22222222-2222-4222-8222-222222222222');

insert into public.projects(id, owner_id, title)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', '11111111-1111-4111-8111-111111111111', 'Test project');

insert into public.studio_projects(id, user_id) values
  ('dddddddd-dddd-4ddd-8ddd-dddddddddddd', '11111111-1111-4111-8111-111111111111'),
  ('eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', '22222222-2222-4222-8222-222222222222');
insert into public.studio_scenes(id, user_id, project_id, scene_number) values
  ('ffffffff-ffff-4fff-8fff-ffffffffffff', '11111111-1111-4111-8111-111111111111',
   'dddddddd-dddd-4ddd-8ddd-dddddddddddd', 1),
  ('abababab-abab-4bab-8bab-abababababab', '22222222-2222-4222-8222-222222222222',
   'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', 1);

insert into public.generation_jobs(
  id, user_id, project_id, job_type, provider, model, idempotency_key, request_hash
) values
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', '11111111-1111-4111-8111-111111111111',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'video_generation', 'test-provider', 'test-model',
   'test-key-user-one', repeat('a', 64)),
  ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', '22222222-2222-4222-8222-222222222222',
   null, 'image_generation', 'test-provider', 'test-model',
   'test-key-user-two', repeat('b', 64));

update public.generation_jobs
set studio_scene_id = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

insert into public.studio_media(user_id, project_id, scene_id, generation_job_id, media_type, storage_path)
values ('11111111-1111-4111-8111-111111111111',
        'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        'ffffffff-ffff-4fff-8fff-ffffffffffff',
        'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        'image', '11111111-1111-4111-8111-111111111111/projects/test/scenes/scene-1/image.png');

insert into public.outbox_events(aggregate_type, aggregate_id, event_type, payload)
values ('generation_job', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        'generation_job.created', '{"test": true}'::jsonb);



-- Scene-bound creation is atomic, owner-scoped, and idempotent.
do $$
declare
  v_first record;
  v_second record;
  v_event_count integer;
begin
  select * into v_first from public.create_scene_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111',
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    'image_generation', 'test-image-provider', 'test-image-model',
    'scene-job-idempotency-1', repeat('d', 64),
    '{"prompt":"scene image test"}'::jsonb, '{}'::jsonb
  );
  select * into v_second from public.create_scene_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111',
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    'image_generation', 'test-image-provider', 'test-image-model',
    'scene-job-idempotency-1', repeat('d', 64),
    '{"prompt":"scene image test"}'::jsonb, '{}'::jsonb
  );
  if not v_first.created or v_second.created
     or v_first.job_id <> v_second.job_id
     or v_first.event_id is distinct from v_second.event_id then
    raise exception 'Scene job idempotency did not return the original job and event';
  end if;
  if not exists (select 1 from public.generation_jobs
                 where id = v_first.job_id
                   and user_id = '11111111-1111-4111-8111-111111111111'
                   and studio_scene_id = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
                   and project_id is null) then
    raise exception 'Scene job was not stored with the correct owner and scene';
  end if;
  select count(*) into v_event_count from public.outbox_events
    where aggregate_id = v_first.job_id and event_type = 'generation_job.created';
  if v_event_count <> 1 then raise exception 'Expected one scene-job outbox event'; end if;

  begin
    perform public.create_scene_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      'ffffffff-ffff-4fff-8fff-ffffffffffff',
      'image_generation', 'test-image-provider', 'test-image-model',
      'cross-owner-scene-key', repeat('c', 64), '{}'::jsonb, '{}'::jsonb
    );
    raise exception 'Cross-owner scene job creation was accepted';
  exception when foreign_key_violation then null;
  end;

  begin
    perform public.create_scene_generation_job_with_outbox(
      '11111111-1111-4111-8111-111111111111',
      'ffffffff-ffff-4fff-8fff-ffffffffffff',
      'image_generation', 'test-image-provider', 'test-image-model',
      'scene-job-idempotency-1', repeat('e', 64), '{}'::jsonb, '{}'::jsonb
    );
    raise exception 'Mismatched scene-job idempotency replay was accepted';
  exception when sqlstate '22023' then null;
  end;
end;
$$;

-- Worker lifecycle: atomic claim, lease ownership, retry, and verified-result completion.
do $$
declare
  v_job_id uuid;
  v_claim record;
  v_second_claim record;
  v_ok boolean;
  v_status text;
begin
  select id into v_job_id
    from public.generation_jobs
   where idempotency_key = 'scene-job-idempotency-1';

  update public.generation_jobs
     set status = 'failed', completed_at = now(), updated_at = now()
   where id <> v_job_id and status in ('queued', 'retry_wait');

  select * into v_claim
    from public.claim_next_generation_job('worker-alpha', 120);
  if v_claim.job_id is distinct from v_job_id or v_claim.attempt_count <> 1 then
    raise exception 'Worker did not atomically claim the expected scene job';
  end if;

  select * into v_second_claim
    from public.claim_next_generation_job('worker-beta', 120);
  if v_second_claim.job_id is not null then
    raise exception 'A second worker claimed a job with an active lease';
  end if;

  if public.heartbeat_generation_job(v_job_id, 'worker-beta', 120) then
    raise exception 'A different worker extended a lease it does not own';
  end if;
  if not public.heartbeat_generation_job(v_job_id, 'worker-alpha', 120) then
    raise exception 'The lease owner could not extend its active lease';
  end if;

  if not public.retry_generation_job(v_job_id, 'worker-alpha', 'provider_temporary_error', 30) then
    raise exception 'The active lease owner could not schedule a retry';
  end if;
  select status into v_status from public.generation_jobs where id = v_job_id;
  if v_status <> 'retry_wait' then
    raise exception 'Retry did not move the job to retry_wait';
  end if;

  update public.generation_jobs set available_at = now() where id = v_job_id;
  select * into v_claim
    from public.claim_next_generation_job('worker-beta', 120);
  if v_claim.job_id is distinct from v_job_id or v_claim.attempt_count <> 2 then
    raise exception 'Retry job was not claimed by the next worker attempt';
  end if;

  if public.complete_generation_job(
    v_job_id, 'worker-alpha',
    '11111111-1111-4111-8111-111111111111/results/image.png'
  ) then
    raise exception 'A worker without the active lease completed the job';
  end if;
  if public.complete_generation_job(
    v_job_id, 'worker-beta',
    '22222222-2222-4222-8222-222222222222/results/image.png'
  ) then
    raise exception 'A worker stored a result under another user path';
  end if;
  if not public.complete_generation_job(
    v_job_id, 'worker-beta',
    '11111111-1111-4111-8111-111111111111/results/image.png'
  ) then
    raise exception 'The active worker could not complete with an owner-scoped result path';
  end if;

  select status into v_status from public.generation_jobs where id = v_job_id;
  if v_status <> 'succeeded' then
    raise exception 'Completed job did not enter succeeded state';
  end if;
end;
$$;

-- Expired leases are rejected, reclaimed within the attempt budget, then terminally failed.
do $lease_test$
declare
  v_created record;
  v_claim record;
  v_job_id uuid;
  v_status text;
begin
  select * into v_created from public.create_scene_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111',
    'ffffffff-ffff-4fff-8fff-ffffffffffff',
    'image_generation', 'test-image-provider', 'test-image-model',
    'lease-expiry-idempotency-1', repeat('f', 64),
    '{"prompt":"lease expiry test"}'::jsonb, '{}'::jsonb
  );
  v_job_id := v_created.job_id;

  select * into v_claim from public.claim_next_generation_job('worker-expiry-a', 30);
  if v_claim.job_id is distinct from v_job_id or v_claim.attempt_count <> 1 then
    raise exception 'First worker did not claim the lease-expiry test job';
  end if;

  update public.generation_jobs
     set lease_expires_at = now() - interval '1 second'
   where id = v_job_id;

  if public.heartbeat_generation_job(v_job_id, 'worker-expiry-a', 30) then
    raise exception 'Heartbeat accepted an expired lease';
  end if;
  if public.complete_generation_job(
    v_job_id, 'worker-expiry-a',
    '11111111-1111-4111-8111-111111111111/results/expired.png'
  ) then
    raise exception 'Completion accepted an expired lease';
  end if;

  select * into v_claim from public.claim_next_generation_job('worker-expiry-b', 30);
  if v_claim.job_id is distinct from v_job_id or v_claim.attempt_count <> 2 then
    raise exception 'An expired lease was not reclaimed as attempt two';
  end if;

  update public.generation_jobs
     set lease_expires_at = now() - interval '1 second'
   where id = v_job_id;

  select * into v_claim from public.claim_next_generation_job('worker-expiry-c', 30);
  if v_claim.job_id is distinct from v_job_id or v_claim.attempt_count <> 3 then
    raise exception 'The final permitted attempt was not reclaimed';
  end if;

  update public.generation_jobs
     set lease_expires_at = now() - interval '1 second'
   where id = v_job_id;

  select * into v_claim from public.claim_next_generation_job('worker-expiry-d', 30);
  if v_claim.job_id is not null then
    raise exception 'An exhausted expired job was claimed again';
  end if;

  select status into v_status from public.generation_jobs where id = v_job_id;
  if v_status <> 'failed' then
    raise exception 'An exhausted expired lease was not moved to failed';
  end if;
end;
$lease_test$;

-- Outbox delivery leases, worker ownership, retry, and dead-letter behavior.
do $outbox_test$
declare
  v_created record;
  v_claim record;
  v_retry_created record;
  v_retry_claim record;
  v_event_id uuid;
  v_retry_event_id uuid;
  v_failed_at timestamptz;
begin
  -- Isolate the test from earlier fixture events.
  update public.outbox_events
     set published_at = now(), lease_owner = null, lease_expires_at = null
   where published_at is null and failed_at is null;

  select * into v_created from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'test-provider', 'test-model',
    'outbox-delivery-idempotency-1', repeat('a', 64),
    '{"prompt":"outbox delivery test"}'::jsonb, '{}'::jsonb
  );
  select event_id into v_event_id
    from public.outbox_events where aggregate_id = v_created.job_id;

  select * into v_claim from public.claim_next_outbox_event('outbox-worker-a', 60);
  if v_claim.event_id is distinct from v_event_id or v_claim.delivery_attempts <> 1 then
    raise exception 'Outbox worker did not claim the expected event';
  end if;

  select * into v_claim from public.claim_next_outbox_event('outbox-worker-b', 60);
  if v_claim.event_id is not null then
    raise exception 'A second outbox worker claimed an event with an active lease';
  end if;
  if public.mark_outbox_event_published(v_event_id, 'outbox-worker-b') then
    raise exception 'A worker without the lease published the event';
  end if;
  if not public.mark_outbox_event_published(v_event_id, 'outbox-worker-a') then
    raise exception 'The active outbox lease owner could not publish the event';
  end if;

  select * into v_retry_created from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'test-provider', 'test-model',
    'outbox-retry-idempotency-1', repeat('b', 64),
    '{"prompt":"outbox retry test"}'::jsonb, '{}'::jsonb
  );
  select event_id into v_retry_event_id
    from public.outbox_events where aggregate_id = v_retry_created.job_id;
  update public.outbox_events
     set max_delivery_attempts = 2
   where event_id = v_retry_event_id;

  select * into v_retry_claim
    from public.claim_next_outbox_event('outbox-retry-worker-a', 60);
  if v_retry_claim.event_id is distinct from v_retry_event_id
     or v_retry_claim.delivery_attempts <> 1 then
    raise exception 'Outbox retry fixture was not claimed on attempt one';
  end if;
  if not public.retry_outbox_event(v_retry_event_id, 'outbox-retry-worker-a', 'broker_unavailable', 1) then
    raise exception 'Outbox retry was not scheduled';
  end if;

  update public.outbox_events set available_at = now()
   where event_id = v_retry_event_id;
  select * into v_retry_claim
    from public.claim_next_outbox_event('outbox-retry-worker-b', 60);
  if v_retry_claim.event_id is distinct from v_retry_event_id
     or v_retry_claim.delivery_attempts <> 2 then
    raise exception 'Outbox event was not reclaimed on its second attempt';
  end if;
  if not public.retry_outbox_event(v_retry_event_id, 'outbox-retry-worker-b', 'broker_unavailable', 1) then
    raise exception 'Final outbox retry attempt was not accepted';
  end if;

  select failed_at into v_failed_at
    from public.outbox_events where event_id = v_retry_event_id;
  if v_failed_at is null then
    raise exception 'Outbox event was not dead-lettered after exhausting attempts';
  end if;
  select * into v_claim from public.claim_next_outbox_event('outbox-worker-c', 60);
  if v_claim.event_id is not null then
    raise exception 'A dead-lettered outbox event was claimed again';
  end if;
end;
$outbox_test$;

-- Only the trusted backend service role may execute worker lifecycle RPCs.
do $$
begin
  if has_function_privilege('authenticated',
       'public.claim_next_generation_job(text,integer)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.heartbeat_generation_job(uuid,text,integer)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.retry_generation_job(uuid,text,text,integer)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.complete_generation_job(uuid,text,text)', 'EXECUTE') then
    raise exception 'Authenticated role unexpectedly has worker RPC execute permission';
  end if;
  if not has_function_privilege('service_role',
       'public.claim_next_generation_job(text,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.heartbeat_generation_job(uuid,text,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.retry_generation_job(uuid,text,text,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.complete_generation_job(uuid,text,text)', 'EXECUTE') then
    raise exception 'service_role is missing a worker lifecycle RPC grant';
  end if;
end;
$$;

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
do $$
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
$$;

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
select 1 / case when count(*) = 4 then 1 else 0 end as assert_only_own_jobs_visible
from public.generation_jobs;
select 1 / case when not has_table_privilege('authenticated', 'public.generation_jobs', 'INSERT') then 1 else 0 end
  as assert_clients_cannot_insert_jobs;
select 1 / case when not has_table_privilege('authenticated', 'public.outbox_events', 'INSERT') then 1 else 0 end
  as assert_clients_cannot_insert_outbox;
reset role;
reset request.jwt.claim.sub;

-- A job cannot be linked to another user's scene.
do $$
begin
  begin
    update public.generation_jobs
    set studio_scene_id = 'abababab-abab-4bab-8bab-abababababab'
    where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
    raise exception 'Cross-owner scene link was accepted';
  exception when foreign_key_violation then
    null;
  end;
end;
$$;

-- Media cannot claim another user's scene or a mismatched studio project.
do $$
begin
  begin
    insert into public.studio_media(user_id, project_id, scene_id, media_type, storage_path)
    values ('11111111-1111-4111-8111-111111111111',
            'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
            'abababab-abab-4bab-8bab-abababababab',
            'image', '11111111-1111-4111-8111-111111111111/forbidden.png');
    raise exception 'Cross-owner media scene link was accepted';
  exception when foreign_key_violation then
    null;
  end;
end;
$$;

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

-- Deleting a scene detaches optional scene references without deleting the saved media or job.
delete from public.studio_scenes where id = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
do $$
begin
  if not exists (select 1 from public.generation_jobs
                 where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
                   and studio_scene_id is null) then
    raise exception 'Deleting a scene did not detach its generation job';
  end if;
  if not exists (select 1 from public.studio_media
                 where generation_job_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
                   and scene_id is null) then
    raise exception 'Deleting a scene did not preserve media and detach its scene reference';
  end if;
end;
$$;

select 'generation jobs and movie scene migration integration checks passed' as result;
