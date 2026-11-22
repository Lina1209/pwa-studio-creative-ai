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
\ir ../migrations/0015_generation_job_terminal_failure.sql
\ir ../migrations/0016_harden_generation_job_idempotency.sql
\ir ../migrations/0017_generation_provider_operation_journal.sql
\ir ../migrations/0018_credit_ledger_schema.sql
\ir ../migrations/0019_credit_hold_lifecycle.sql
\ir ../migrations/0020_atomic_credited_generation.sql
\ir ../migrations/0021_persist_pricing_quotes.sql
\ir ../migrations/0022_generation_provider_cost_events.sql
\ir ../migrations/0023_release_credits_on_terminal_worker_states.sql
\ir ../migrations/0024_generation_result_sha256.sql

-- Credit accounting tables are mutated only by SECURITY DEFINER transaction RPCs.
do $credit_ledger_privileges_test$
begin
  if has_table_privilege('service_role', 'public.credit_wallets', 'INSERT')
     or has_table_privilege('service_role', 'public.credit_wallets', 'UPDATE')
     or has_table_privilege('service_role', 'public.credit_wallets', 'DELETE')
     or has_table_privilege('service_role', 'public.credit_wallets', 'TRUNCATE')
     or has_table_privilege('service_role', 'public.credit_holds', 'INSERT')
     or has_table_privilege('service_role', 'public.credit_holds', 'UPDATE')
     or has_table_privilege('service_role', 'public.credit_holds', 'DELETE')
     or has_table_privilege('service_role', 'public.credit_holds', 'TRUNCATE')
     or has_table_privilege('service_role', 'public.credit_ledger', 'INSERT')
     or has_table_privilege('service_role', 'public.credit_ledger', 'UPDATE')
     or has_table_privilege('service_role', 'public.credit_ledger', 'DELETE')
     or has_table_privilege('service_role', 'public.credit_ledger', 'TRUNCATE')
     or not has_table_privilege('service_role', 'public.credit_wallets', 'SELECT')
     or not has_table_privilege('service_role', 'public.credit_holds', 'SELECT')
     or not has_table_privilege('service_role', 'public.credit_ledger', 'SELECT') then
    raise exception 'Service role can bypass credit lifecycle RPCs or cannot read accounting state';
  end if;
  if has_function_privilege('authenticated',
       'public.grant_user_credits(uuid,bigint,text,jsonb)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.reserve_job_credits(uuid,uuid,bigint,text,jsonb)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.release_job_credit_hold(uuid,uuid,text)', 'EXECUTE') then
    raise exception 'Authenticated role unexpectedly has credit mutation RPC privileges';
  end if;
end;
$credit_ledger_privileges_test$;



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

-- Generic job creation validates idempotency inputs and returns the same job/event.
do $generic_idempotency$
declare
  v_first record;
  v_replay record;
  v_count integer;
  v_rejected boolean;
begin
  select * into v_first from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'generic-provider', 'generic-model',
    'generic-idempotency-001', repeat('a', 64),
    '{"prompt":"same canonical request"}'::jsonb, '{"price_version":"v1"}'::jsonb
  );
  select * into v_replay from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'generic-provider', 'generic-model',
    'generic-idempotency-001', repeat('a', 64),
    '{"prompt":"same canonical request"}'::jsonb, '{"price_version":"v1"}'::jsonb
  );
  if not v_first.created or v_replay.created
     or v_first.job_id <> v_replay.job_id
     or v_first.event_id <> v_replay.event_id then
    raise exception 'Generic idempotent replay did not return original job and event';
  end if;
  select count(*) into v_count from public.outbox_events
   where aggregate_id = v_first.job_id and event_type = 'generation_job.created';
  if v_count <> 1 then raise exception 'Generic replay created a duplicate outbox event'; end if;

  v_rejected := false;
    begin
      perform public.create_generation_job_with_outbox(
        '11111111-1111-4111-8111-111111111111', null,
        'image_generation', 'generic-provider', 'generic-model',
        'generic-idempotency-001', repeat('b', 64), '{}'::jsonb, '{}'::jsonb
      );
    exception when sqlstate '22023' then v_rejected := true;
    end;
    if not v_rejected then raise exception 'Mismatched generic idempotency replay was accepted'; end if;

    v_rejected := false;
    begin
      perform public.create_generation_job_with_outbox(
        '11111111-1111-4111-8111-111111111111', null,
        'image_generation', 'generic-provider', 'generic-model',
        'short', repeat('c', 64), '{}'::jsonb, '{}'::jsonb
      );
    exception when sqlstate '22023' then v_rejected := true;
    end;
    if not v_rejected then raise exception 'Short idempotency key was accepted'; end if;

    v_rejected := false;
    begin
      perform public.create_generation_job_with_outbox(
        '11111111-1111-4111-8111-111111111111', null,
        'image_generation', 'generic-provider', 'generic-model',
        'generic-invalid-hash-001', 'not-a-valid-hash', '{}'::jsonb, '{}'::jsonb
      );
    exception when sqlstate '22023' then v_rejected := true;
    end;
    if not v_rejected then raise exception 'Malformed request hash was accepted'; end if;
end;
$generic_idempotency$;

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
  v_lease_created record;
  v_lease_claim record;
  v_lease_event_id uuid;
  v_failed_at timestamptz;
  v_lease_failed_at timestamptz;
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

  select * into v_lease_created from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'test-provider', 'test-model',
    'outbox-lease-expiry-idempotency-1', repeat('c', 64),
    '{"prompt":"outbox lease expiry test"}'::jsonb, '{}'::jsonb
  );
  select event_id into v_lease_event_id
    from public.outbox_events where aggregate_id = v_lease_created.job_id;
  update public.outbox_events
     set max_delivery_attempts = 2
   where event_id = v_lease_event_id;

  select * into v_lease_claim
    from public.claim_next_outbox_event('outbox-lease-worker-a', 60);
  if v_lease_claim.event_id is distinct from v_lease_event_id
     or v_lease_claim.delivery_attempts <> 1 then
    raise exception 'Outbox lease-expiry fixture was not claimed on attempt one';
  end if;
  update public.outbox_events
     set lease_expires_at = now() - interval '1 second'
   where event_id = v_lease_event_id;
  if public.mark_outbox_event_published(v_lease_event_id, 'outbox-lease-worker-a') then
    raise exception 'Expired outbox lease was allowed to acknowledge delivery';
  end if;

  select * into v_lease_claim
    from public.claim_next_outbox_event('outbox-lease-worker-b', 60);
  if v_lease_claim.event_id is distinct from v_lease_event_id
     or v_lease_claim.delivery_attempts <> 2 then
    raise exception 'Expired outbox lease was not reclaimed as attempt two';
  end if;
  update public.outbox_events
     set lease_expires_at = now() - interval '1 second'
   where event_id = v_lease_event_id;
  select * into v_lease_claim
    from public.claim_next_outbox_event('outbox-lease-worker-c', 60);
  if v_lease_claim.event_id is not null then
    raise exception 'An exhausted expired outbox lease was claimed again';
  end if;
  select failed_at into v_lease_failed_at
    from public.outbox_events where event_id = v_lease_event_id;
  if v_lease_failed_at is null then
    raise exception 'An exhausted expired outbox lease was not dead-lettered';
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
       'public.complete_generation_job(uuid,text,text)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.fail_generation_job(uuid,text,text)', 'EXECUTE') then
    raise exception 'Authenticated role unexpectedly has worker RPC execute permission';
  end if;
  if not has_function_privilege('service_role',
       'public.claim_next_generation_job(text,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.heartbeat_generation_job(uuid,text,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.retry_generation_job(uuid,text,text,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.complete_generation_job(uuid,text,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.fail_generation_job(uuid,text,text)', 'EXECUTE') then
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
select 1 / case when count(*) = 8 then 1 else 0 end as assert_only_own_jobs_visible
from public.generation_jobs;
select 1 / case when not has_table_privilege('authenticated', 'public.generation_jobs', 'INSERT') then 1 else 0 end
  as assert_clients_cannot_insert_jobs;
select 1 / case when not has_table_privilege('authenticated', 'public.outbox_events', 'INSERT') then 1 else 0 end
  as assert_clients_cannot_insert_outbox;
reset role;
reset request.jwt.claim.sub;

-- Non-retryable worker errors have an explicit terminal path, guarded by the active lease.
do $terminal_failure_test$
declare
  v_created record;
  v_claim record;
  v_job_id uuid;
  v_status text;
  v_completed_at timestamptz;
  v_lease_owner text;
begin
  select * into v_created from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'test-provider', 'test-model',
    'terminal-failure-idempotency-1', repeat('d', 64),
    '{"prompt":"terminal failure contract"}'::jsonb, '{}'::jsonb
  );
  v_job_id := v_created.job_id;

  update public.generation_jobs
     set status = 'failed', completed_at = now(), updated_at = now()
   where id <> v_job_id and status in ('queued', 'retry_wait');

  select * into v_claim from public.claim_next_generation_job('worker-terminal-failure', 60);
  if v_claim.job_id is distinct from v_job_id then
    raise exception 'Terminal failure fixture was not claimed';
  end if;
  if public.fail_generation_job(v_job_id, 'different-worker', 'provider_rejected') then
    raise exception 'A worker without the active lease failed the job';
  end if;
  if not public.fail_generation_job(v_job_id, 'worker-terminal-failure', 'provider_rejected') then
    raise exception 'The active worker could not mark a permanent failure';
  end if;

  select status, completed_at, lease_owner
    into v_status, v_completed_at, v_lease_owner
    from public.generation_jobs where id = v_job_id;
  if v_status <> 'failed' or v_completed_at is null or v_lease_owner is not null then
    raise exception 'Terminal failure did not clear the lease and set completion metadata';
  end if;
  if public.heartbeat_generation_job(v_job_id, 'worker-terminal-failure', 60)
     or public.retry_generation_job(v_job_id, 'worker-terminal-failure', 'retry_after_terminal', 30)
     or public.complete_generation_job(
       v_job_id, 'worker-terminal-failure',
       '11111111-1111-4111-8111-111111111111/results/should-not-exist.png'
     ) then
    raise exception 'A terminally failed job accepted another lifecycle transition';
  end if;
end;
$terminal_failure_test$;


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



-- Provider-operation journal: durable identity, lease ownership, monotonic state and privileges.
do $provider_journal_test$
declare
  v_created record;
  v_replay record;
  v_claim record;
  v_job_id uuid;
  v_operation_id uuid;
  v_state text;
  v_request_id text;
begin
  -- Isolate this fixture so the claim target is deterministic.
  update public.generation_jobs
     set status = 'failed', completed_at = now(), updated_at = now()
   where status in ('queued', 'retry_wait');

  select * into v_created
    from public.create_generation_job_with_outbox(
      '11111111-1111-4111-8111-111111111111', null,
      'image_generation', 'journal-provider', 'journal-model',
      'provider-journal-request-key-001', repeat('9', 64),
      '{"prompt":"provider journal integration"}'::jsonb, '{}'::jsonb
    );
  v_job_id := v_created.job_id;

  select * into v_claim
    from public.claim_next_generation_job('journal-worker-a', 120);
  if v_claim.job_id is distinct from v_job_id then
    raise exception 'Provider journal fixture was not claimed';
  end if;

  select * into v_created
    from public.begin_generation_provider_operation(
      v_job_id, 'journal-worker-a', 'journal-provider', v_job_id::text
    );
  if not v_created.created or v_created.operation_state <> 'submitting' then
    raise exception 'First provider journal begin did not create submitting row';
  end if;
  v_operation_id := v_created.operation_id;

  select * into v_replay
    from public.begin_generation_provider_operation(
      v_job_id, 'journal-worker-a', 'journal-provider', v_job_id::text
    );
  if v_replay.created or v_replay.operation_id <> v_operation_id
     or v_replay.operation_state <> 'submitting' then
    raise exception 'Provider journal replay did not return the original row';
  end if;

  begin
    perform public.begin_generation_provider_operation(
      v_job_id, 'journal-worker-a', 'different-provider', v_job_id::text
    );
    raise exception 'Provider identity mismatch was accepted';
  exception when sqlstate '22023' then null;
  end;

  begin
    perform public.begin_generation_provider_operation(
      v_job_id, 'journal-worker-a', 'journal-provider', 'client-request-key'
    );
    raise exception 'Client request key was accepted as provider key';
  exception when sqlstate '22023' then null;
  end;

  if public.mark_generation_provider_operation_unknown(
       v_job_id, 'wrong-worker', 'response_lost') then
    raise exception 'A different worker changed provider journal state';
  end if;
  if not public.mark_generation_provider_operation_unknown(
       v_job_id, 'journal-worker-a', 'response_lost') then
    raise exception 'Lease owner could not mark ambiguous provider operation';
  end if;

  if not public.mark_generation_provider_operation_accepted(
       v_job_id, 'journal-worker-a', 'provider-request-123'
     ) then
    raise exception 'Lease owner could not record provider acceptance after lookup';
  end if;
  if public.mark_generation_provider_operation_accepted(
       v_job_id, 'journal-worker-a', 'conflicting-provider-request'
     ) then
    raise exception 'Conflicting provider request ID overwrote durable identity';
  end if;

  if not public.mark_generation_provider_operation_result_received(
       v_job_id, 'journal-worker-a', 'provider-request-123'
     ) then
    raise exception 'Lease owner could not record received provider result';
  end if;
  if public.mark_generation_provider_operation_unknown(
       v_job_id, 'journal-worker-a', 'late_ambiguous_response'
     ) then
    raise exception 'A stale unknown transition overwrote result_received';
  end if;

  update public.generation_jobs
     set lease_expires_at = now() - interval '1 second'
   where id = v_job_id;
  if public.mark_generation_provider_operation_result_received(
       v_job_id, 'journal-worker-a', 'provider-request-123'
     ) then
    raise exception 'An expired lease changed provider journal state';
  end if;
  update public.generation_jobs
     set lease_expires_at = now() + interval '120 seconds'
   where id = v_job_id;

  select state, provider_request_id
    into v_state, v_request_id
    from public.generation_provider_operations where job_id = v_job_id;
  if v_state <> 'result_received' or v_request_id <> 'provider-request-123' then
    raise exception 'Provider journal terminal result metadata is inconsistent';
  end if;

  if not public.heartbeat_generation_job(v_job_id, 'journal-worker-a', 120) then
    raise exception 'Journal fixture lease unexpectedly expired';
  end if;
  if not public.complete_generation_job(
       v_job_id, 'journal-worker-a',
       '11111111-1111-4111-8111-111111111111/generated/provider-journal.png'
     ) then
    raise exception 'Journal fixture job could not complete';
  end if;

  if has_table_privilege('authenticated', 'public.generation_provider_operations', 'SELECT')
     or has_table_privilege('authenticated', 'public.generation_provider_operations', 'INSERT')
     or has_table_privilege('authenticated', 'public.generation_provider_operations', 'UPDATE')
     or has_table_privilege('authenticated', 'public.generation_provider_operations', 'DELETE') then
    raise exception 'Authenticated role unexpectedly has provider journal table privileges';
  end if;
  if has_function_privilege('authenticated',
       'public.begin_generation_provider_operation(uuid,text,text,text)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.mark_generation_provider_operation_accepted(uuid,text,text)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.mark_generation_provider_operation_unknown(uuid,text,text)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.mark_generation_provider_operation_failed(uuid,text,text)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.mark_generation_provider_operation_result_received(uuid,text,text)', 'EXECUTE') then
    raise exception 'Authenticated role unexpectedly has provider journal RPC privileges';
  end if;
  if not has_function_privilege('service_role',
       'public.begin_generation_provider_operation(uuid,text,text,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.mark_generation_provider_operation_accepted(uuid,text,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.mark_generation_provider_operation_unknown(uuid,text,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.mark_generation_provider_operation_failed(uuid,text,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.mark_generation_provider_operation_result_received(uuid,text,text)', 'EXECUTE') then
    raise exception 'service_role is missing provider journal RPC grants';
  end if;
end;
$provider_journal_test$;




-- Credit ledger schema: owner isolation, positive constraints and append-only history.
do $credit_ledger_schema_test$
declare
  v_hold_id uuid;
  v_wallet_id uuid;
  v_cross_owner_job_id uuid;
begin
  insert into public.credit_wallets(user_id, available_credits, reserved_credits)
  values
    ('11111111-1111-4111-8111-111111111111', 100, 0),
    ('22222222-2222-4222-8222-222222222222', 50, 0);

  select id into v_wallet_id from public.credit_wallets
   where user_id = '11111111-1111-4111-8111-111111111111';
  if v_wallet_id is null then raise exception 'Wallet was not created'; end if;

  insert into public.credit_holds(
    user_id, job_id, amount, quote_snapshot, operation_key
  ) values (
    '11111111-1111-4111-8111-111111111111',
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    10, '{"price_version":"test-v1","approved_maximum":10}'::jsonb,
    'test-reserve-operation-001'
  ) returning id into v_hold_id;

  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    '11111111-1111-4111-8111-111111111111', v_hold_id,
    'reserve', 'test-ledger-reserve-001',
    -10, 10, 90, 10, '{"test_fixture":true}'::jsonb
  );

  begin
    update public.credit_ledger
       set metadata = '{"tampered":true}'::jsonb
     where operation_key = 'test-ledger-reserve-001';
    raise exception 'Ledger UPDATE was accepted';
  exception when sqlstate '55000' then null;
  end;

  begin
    delete from public.credit_ledger
     where operation_key = 'test-ledger-reserve-001';
    raise exception 'Ledger DELETE was accepted';
  exception when sqlstate '55000' then null;
  end;

  select id into v_cross_owner_job_id
    from public.generation_jobs
   where user_id = '11111111-1111-4111-8111-111111111111'
     and idempotency_key = 'generic-idempotency-001';
  if v_cross_owner_job_id is null then
    raise exception 'Cross-owner test fixture job was not found';
  end if;

  begin
    insert into public.credit_holds(
      user_id, job_id, amount, quote_snapshot, operation_key
    ) values (
      '22222222-2222-4222-8222-222222222222',
      v_cross_owner_job_id,
      5, '{}'::jsonb, 'cross-owner-hold-001'
    );
    raise exception 'Cross-owner credit hold was accepted';
  exception when foreign_key_violation then null;
  end;

  if has_table_privilege('authenticated', 'public.credit_wallets', 'INSERT')
     or has_table_privilege('authenticated', 'public.credit_wallets', 'UPDATE')
     or has_table_privilege('authenticated', 'public.credit_wallets', 'DELETE')
     or has_table_privilege('authenticated', 'public.credit_holds', 'INSERT')
     or has_table_privilege('authenticated', 'public.credit_holds', 'UPDATE')
     or has_table_privilege('authenticated', 'public.credit_holds', 'DELETE')
     or has_table_privilege('authenticated', 'public.credit_ledger', 'INSERT')
     or has_table_privilege('authenticated', 'public.credit_ledger', 'UPDATE')
     or has_table_privilege('authenticated', 'public.credit_ledger', 'DELETE') then
    raise exception 'Authenticated role unexpectedly has credit mutation privileges';
  end if;

  if not has_table_privilege('authenticated', 'public.credit_wallets', 'SELECT')
     or not has_table_privilege('authenticated', 'public.credit_holds', 'SELECT')
     or not has_table_privilege('authenticated', 'public.credit_ledger', 'SELECT') then
    raise exception 'Authenticated role is missing read access governed by RLS';
  end if;
end;
$credit_ledger_schema_test$;




-- Credit lifecycle RPCs: idempotent grant/reserve/release and guarded balance arithmetic.
do $credit_lifecycle_rpc_test$
declare
  v_grant record;
  v_grant_replay record;
  v_hold record;
  v_hold_replay record;
  v_release record;
  v_release_replay record;
  v_job_id uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_insufficient_job_id uuid;
  v_hold_id uuid;
  v_rejected boolean;
  v_ledger_count integer;
begin
  select * into v_grant from public.grant_user_credits(
    '22222222-2222-4222-8222-222222222222', 25,
    'integration-test-grant-001', '{"source":"test"}'::jsonb
  );
  if v_grant.available_credits <> 75 or v_grant.reserved_credits <> 0 or v_grant.replayed then
    raise exception 'Initial credit grant produced unexpected wallet balances';
  end if;

  select * into v_grant_replay from public.grant_user_credits(
    '22222222-2222-4222-8222-222222222222', 25,
    'integration-test-grant-001', '{"source":"test"}'::jsonb
  );
  if not v_grant_replay.replayed or v_grant_replay.available_credits <> 75 then
    raise exception 'Duplicate credit grant was not idempotent';
  end if;

  v_rejected := false;
  begin
    perform public.grant_user_credits(
      '22222222-2222-4222-8222-222222222222', 26,
      'integration-test-grant-001', '{"source":"test"}'::jsonb
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Mismatched grant replay was accepted'; end if;

  -- Earlier worker lifecycle tests may have terminalized this fixture job.
  -- Restore an eligible state before testing the standalone reservation RPC.
  update public.generation_jobs
     set status = 'queued', completed_at = null, last_error_code = null,
         lease_owner = null, lease_expires_at = null, heartbeat_at = null,
         updated_at = now()
   where id = v_job_id;

  select * into v_hold from public.reserve_job_credits(
    '22222222-2222-4222-8222-222222222222', v_job_id, 20,
    'integration-test-reserve-001',
    '{"price_version":"test-v1","approved_maximum":20}'::jsonb
  );
  v_hold_id := v_hold.hold_id;
  if v_hold_id is null or v_hold.available_credits <> 55
     or v_hold.reserved_credits <> 20 or v_hold.replayed then
    raise exception 'Credit reservation produced unexpected result';
  end if;

  select * into v_hold_replay from public.reserve_job_credits(
    '22222222-2222-4222-8222-222222222222', v_job_id, 20,
    'integration-test-reserve-001',
    '{"price_version":"test-v1","approved_maximum":20}'::jsonb
  );
  if v_hold_replay.hold_id <> v_hold_id or not v_hold_replay.replayed
     or v_hold_replay.available_credits <> 55
     or v_hold_replay.reserved_credits <> 20 then
    raise exception 'Duplicate reservation changed wallet or hold identity';
  end if;

  v_rejected := false;
  begin
    perform public.reserve_job_credits(
      '22222222-2222-4222-8222-222222222222', v_job_id, 21,
      'integration-test-reserve-001',
      '{"price_version":"test-v1","approved_maximum":21}'::jsonb
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Mismatched reservation replay was accepted'; end if;

  select job_id into v_insufficient_job_id
    from public.create_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222', null,
      'image_generation', 'credit-test-provider', 'credit-test-model',
      'integration-test-insufficient-job-001', repeat('9', 64),
      '{}'::jsonb, '{}'::jsonb
    );

  v_rejected := false;
  begin
    perform public.reserve_job_credits(
      '22222222-2222-4222-8222-222222222222', v_insufficient_job_id, 100,
      'integration-test-reserve-insufficient',
      '{"price_version":"test-v1","approved_maximum":100}'::jsonb
    );
  exception when sqlstate 'P0001' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Insufficient credit reservation was accepted'; end if;

  update public.generation_jobs
     set status = 'queued', completed_at = null, updated_at = now()
   where id = v_job_id;

  v_rejected := false;
  begin
    perform public.release_job_credit_hold(
      '22222222-2222-4222-8222-222222222222', v_hold_id, 'premature_release'
    );
  exception when sqlstate '55000' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Credit hold was released before job became terminal'; end if;

  update public.generation_jobs
     set status = 'failed', last_error_code = 'test_terminal_failure',
         completed_at = now(), updated_at = now()
   where id = v_job_id;

  select * into v_release from public.release_job_credit_hold(
    '22222222-2222-4222-8222-222222222222', v_hold_id, 'test_terminal_failure'
  );
  if v_release.available_credits <> 75 or v_release.reserved_credits <> 0
     or v_release.replayed then
    raise exception 'Credit hold release produced unexpected wallet balances';
  end if;

  v_rejected := false;
  begin
    perform public.release_job_credit_hold(
      '22222222-2222-4222-8222-222222222222', v_hold_id, 'different_reason'
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Mismatched release replay reason was accepted'; end if;

  select * into v_release_replay from public.release_job_credit_hold(
    '22222222-2222-4222-8222-222222222222', v_hold_id, 'test_terminal_failure'
  );
  if not v_release_replay.replayed or v_release_replay.available_credits <> 75
     or v_release_replay.reserved_credits <> 0 then
    raise exception 'Duplicate credit release changed wallet balances';
  end if;

  select count(*) into v_ledger_count from public.credit_ledger
   where user_id = '22222222-2222-4222-8222-222222222222';
  if v_ledger_count <> 3 then
    raise exception 'Expected exactly grant, reserve and release ledger entries; got %', v_ledger_count;
  end if;

  if has_function_privilege('authenticated',
       'public.grant_user_credits(uuid,bigint,text,jsonb)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.reserve_job_credits(uuid,uuid,bigint,text,jsonb)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.release_job_credit_hold(uuid,uuid,text)', 'EXECUTE') then
    raise exception 'Authenticated role unexpectedly has credit mutation RPC privileges';
  end if;
  v_rejected := false;
  begin
    delete from auth.users where id = '22222222-2222-4222-8222-222222222222';
  exception when foreign_key_violation then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Account deletion unexpectedly removed append-only ledger history';
  end if;

  if not has_function_privilege('service_role',
       'public.grant_user_credits(uuid,bigint,text,jsonb)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.reserve_job_credits(uuid,uuid,bigint,text,jsonb)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.release_job_credit_hold(uuid,uuid,text)', 'EXECUTE') then
    raise exception 'service_role is missing credit lifecycle RPC grants';
  end if;
end;
$credit_lifecycle_rpc_test$;




-- Atomic paid-generation admission and successful capture.
do $atomic_credited_generation_test$
declare
  v_first record;
  v_replay record;
  v_completed record;
  v_completed_replay record;
  v_job_id uuid;
  v_hold_id uuid;
  v_ledger_count integer;
  v_rejected boolean := false;
begin
  select * into v_first from public.create_credited_generation_job_with_outbox(
    '22222222-2222-4222-8222-222222222222',
    null, null, 'image_generation', 'atomic-test-provider', 'atomic-test-model',
    'atomic-credit-job-0001', repeat('f', 64),
    '{"prompt":"atomic generation test"}'::jsonb,
    '{"price_version":"test-v1","approved_maximum":15}'::jsonb,
    15
  );
  v_job_id := v_first.job_id;
  v_hold_id := v_first.hold_id;
  if not v_first.created or v_first.replayed or v_job_id is null or v_hold_id is null
     or v_first.available_credits <> 60 or v_first.reserved_credits <> 15 then
    raise exception 'Atomic paid-generation admission returned unexpected values';
  end if;

  select * into v_replay from public.create_credited_generation_job_with_outbox(
    '22222222-2222-4222-8222-222222222222',
    null, null, 'image_generation', 'atomic-test-provider', 'atomic-test-model',
    'atomic-credit-job-0001', repeat('f', 64),
    '{"prompt":"atomic generation test"}'::jsonb,
    '{"price_version":"test-v1","approved_maximum":15}'::jsonb,
    15
  );
  if v_replay.job_id <> v_job_id or v_replay.hold_id <> v_hold_id
     or v_replay.event_id <> v_first.event_id
     or v_replay.created or not v_replay.replayed
     or v_replay.available_credits <> 60 or v_replay.reserved_credits <> 15 then
    raise exception 'Atomic paid-generation replay changed job, hold, event or balances';
  end if;

  v_rejected := false;
  begin
    perform public.create_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      null, null, 'image_generation', 'atomic-test-provider', 'atomic-test-model',
      'atomic-insufficient-credit-0001', repeat('e', 64),
      '{"prompt":"must roll back"}'::jsonb,
      '{"price_version":"test-v1","approved_maximum":1000}'::jsonb,
      1000
    );
  exception when sqlstate 'P0001' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Atomic job admission accepted insufficient credits'; end if;
  if exists (select 1 from public.generation_jobs
             where user_id = '22222222-2222-4222-8222-222222222222'
               and idempotency_key = 'atomic-insufficient-credit-0001')
     or exists (select 1 from public.outbox_events e
                join public.generation_jobs j on j.id = e.aggregate_id
                where j.idempotency_key = 'atomic-insufficient-credit-0001')
     or exists (select 1 from public.credit_holds
                where operation_key = 'atomic-insufficient-credit-0001') then
    raise exception 'Failed atomic admission left a partial job, event or hold';
  end if;

  v_rejected := false;
  begin
    perform public.create_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      null, null, 'image_generation', 'atomic-test-provider', 'atomic-test-model',
      'atomic-credit-job-0001', repeat('f', 64),
      '{"prompt":"atomic generation test"}'::jsonb,
      '{"price_version":"test-v1","approved_maximum":16}'::jsonb,
      16
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Atomic job accepted a changed quote on replay'; end if;

  -- Simulate a verified upload and a currently active worker lease.
  update public.generation_jobs
     set status = 'running', lease_owner = 'atomic-test-worker',
         lease_expires_at = now() + interval '120 seconds',
         heartbeat_at = now(), updated_at = now()
   where id = v_job_id;

  v_rejected := false;
  begin
    perform public.complete_credited_generation_job(
      v_job_id, 'atomic-test-worker',
      '22222222-2222-4222-8222-222222222222/generated/atomic-result.png', repeat('g', 64)
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Credited completion accepted a malformed result SHA-256';
  end if;

  select * into v_completed from public.complete_credited_generation_job(
    v_job_id, 'atomic-test-worker',
    '22222222-2222-4222-8222-222222222222/generated/atomic-result.png', repeat('a', 64)
  );
  if not v_completed.completed or v_completed.replayed
     or v_completed.available_credits <> 60 or v_completed.reserved_credits <> 0 then
    raise exception 'Atomic successful completion/capture returned unexpected balances';
  end if;

  select * into v_completed_replay from public.complete_credited_generation_job(
    v_job_id, 'atomic-test-worker',
    '22222222-2222-4222-8222-222222222222/generated/atomic-result.png', repeat('a', 64)
  );
  if not v_completed_replay.completed or not v_completed_replay.replayed
     or v_completed_replay.available_credits <> 60
     or v_completed_replay.reserved_credits <> 0 then
    raise exception 'Repeated successful completion charged credits more than once';
  end if;

  -- A replay with a different result path must not rewrite the durable result.
  v_rejected := false;
  begin
    perform public.complete_credited_generation_job(
      v_job_id, 'different-worker',
      '22222222-2222-4222-8222-222222222222/generated/other-result.png', repeat('b', 64)
  );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Credited completion replay accepted a different result path';
  end if;

  -- Even the same path cannot be replayed with a different content digest.
  v_rejected := false;
  begin
    perform public.complete_credited_generation_job(
      v_job_id, 'atomic-test-worker',
      '22222222-2222-4222-8222-222222222222/generated/atomic-result.png', repeat('d', 64)
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Credited completion replay accepted a different result SHA-256';
  end if;

  if not exists (select 1 from public.credit_holds
                 where id = v_hold_id and status = 'captured' and captured_at is not null) then
    raise exception 'Atomic completion did not capture the hold';
  end if;
  select count(*) into v_ledger_count from public.credit_ledger
   where hold_id = v_hold_id;
  if v_ledger_count <> 2 then
    raise exception 'Expected one reserve and one capture ledger entry; got %', v_ledger_count;
  end if;
  if not exists (select 1 from public.generation_jobs
                 where id = v_job_id and status = 'succeeded'
                   and result_storage_path = '22222222-2222-4222-8222-222222222222/generated/atomic-result.png'
                   and result_sha256 = repeat('a', 64)
                   and lease_owner is null and completed_at is not null) then
    raise exception 'Atomic completion did not finalize the job consistently';
  end if;

  if has_function_privilege('authenticated',
       'public.create_credited_generation_job_with_outbox(uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.complete_credited_generation_job(uuid,text,text,text)', 'EXECUTE') then
    raise exception 'Authenticated role unexpectedly has atomic credited generation RPC privileges';
  end if;
end;
$atomic_credited_generation_test$;


select 'generation jobs, provider journal, credit ledger, atomic admission and capture checks passed' as result;


-- Durable, immutable, owner/idempotency-bound pricing quote persistence.
do $pricing_quote_persistence_test$
declare
  v_first record;
  v_replay record;
  v_candidate jsonb;
  v_original_quote_id uuid;
  v_rejected boolean := false;
  v_expiry timestamptz := now() + interval '5 minutes';
begin
  v_original_quote_id := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_candidate := jsonb_build_object(
    'schema', 'pwa-studio-pricing-quote-v1',
    'quote_id', v_original_quote_id,
    'user_id', '11111111-1111-4111-8111-111111111111',
    'idempotency_key', 'pricing-db-idempotency-001',
    'request_hash', repeat('a', 64),
    'job_type', 'image_generation',
    'provider', 'pricing-test-provider',
    'model', 'pricing-test-model',
    'quantity', 1,
    'project_id', null,
    'studio_scene_id', null,
    'expires_at', v_expiry
  );

  select * into v_first from public.store_generation_pricing_quote(
    v_original_quote_id,
    '11111111-1111-4111-8111-111111111111',
    'pricing-db-idempotency-001',
    repeat('a', 64),
    'image_generation',
    'pricing-test-provider',
    'pricing-test-model',
    null, null, v_candidate, v_expiry
  );
  if not v_first.created or v_first.expired
     or v_first.quote_snapshot ->> 'quote_id' <> v_original_quote_id::text then
    raise exception 'First pricing quote was not persisted as expected';
  end if;

  -- A retry produces a fresh candidate UUID and timestamp, but the database
  -- must return the first immutable quote for this owner/idempotency key.
  v_candidate := jsonb_set(
    v_candidate, '{quote_id}',
    to_jsonb('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'::text)
  );
  select * into v_replay from public.store_generation_pricing_quote(
    'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    '11111111-1111-4111-8111-111111111111',
    'pricing-db-idempotency-001',
    repeat('a', 64),
    'image_generation',
    'pricing-test-provider',
    'pricing-test-model',
    null, null, v_candidate, v_expiry
  );
  if v_replay.created or v_replay.expired
     or v_replay.quote_snapshot ->> 'quote_id' <> v_original_quote_id::text then
    raise exception 'Pricing quote replay did not return the original snapshot';
  end if;

  v_rejected := false;
  begin
    perform public.store_generation_pricing_quote(
      'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      '11111111-1111-4111-8111-111111111111',
      'pricing-db-idempotency-001',
      repeat('b', 64),
      'image_generation',
      'pricing-test-provider',
      'pricing-test-model',
      null, null,
      jsonb_set(
        jsonb_set(v_candidate, '{quote_id}', to_jsonb('cccccccc-cccc-4ccc-8ccc-cccccccccccc'::text)),
        '{request_hash}', to_jsonb(repeat('b', 64))
      ),
      v_expiry
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Pricing quote idempotency key accepted a changed request hash';
  end if;

  v_rejected := false;
  begin
    perform public.store_generation_pricing_quote(
      'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      '11111111-1111-4111-8111-111111111111',
      'pricing-db-idempotency-001',
      repeat('a', 64),
      'image_generation',
      'pricing-test-provider',
      'pricing-test-model',
      null, null,
      jsonb_set(
        jsonb_set(v_candidate, '{quote_id}', to_jsonb('dddddddd-dddd-4ddd-8ddd-dddddddddddd'::text)),
        '{quantity}', to_jsonb(2)
      ),
      v_expiry
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Pricing quote idempotency key accepted a changed quantity';
  end if;

  v_rejected := false;
  begin
    perform public.store_generation_pricing_quote(
      'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      '22222222-2222-4222-8222-222222222222',
      'pricing-foreign-project-001',
      repeat('d', 64),
      'image_generation',
      'pricing-test-provider',
      'pricing-test-model',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      null,
      jsonb_build_object(
        'quote_id', 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
        'user_id', '22222222-2222-4222-8222-222222222222',
        'idempotency_key', 'pricing-foreign-project-001',
        'request_hash', repeat('d', 64),
        'job_type', 'image_generation',
        'provider', 'pricing-test-provider',
        'model', 'pricing-test-model',
        'quantity', 1,
        'project_id', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        'studio_scene_id', null,
        'expires_at', v_expiry
      ),
      v_expiry
    );
  exception when sqlstate '42501' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Pricing quote accepted another user cloud project';
  end if;

  v_rejected := false;
  begin
    perform public.store_generation_pricing_quote(
      'ffffffff-ffff-4fff-8fff-ffffffffffff',
      '22222222-2222-4222-8222-222222222222',
      'pricing-foreign-scene-001',
      repeat('e', 64),
      'image_generation',
      'pricing-test-provider',
      'pricing-test-model',
      null,
      'ffffffff-ffff-4fff-8fff-ffffffffffff',
      jsonb_build_object(
        'quote_id', 'ffffffff-ffff-4fff-8fff-ffffffffffff',
        'user_id', '22222222-2222-4222-8222-222222222222',
        'idempotency_key', 'pricing-foreign-scene-001',
        'request_hash', repeat('e', 64),
        'job_type', 'image_generation',
        'provider', 'pricing-test-provider',
        'model', 'pricing-test-model',
        'quantity', 1,
        'project_id', null,
        'studio_scene_id', 'ffffffff-ffff-4fff-8fff-ffffffffffff',
        'expires_at', v_expiry
      ),
      v_expiry
    );
  exception when sqlstate '42501' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Pricing quote accepted another user studio scene';
  end if;

  v_rejected := false;
  begin
    update public.generation_pricing_quotes
       set quote_snapshot = '{}'::jsonb
     where user_id = '11111111-1111-4111-8111-111111111111'
       and idempotency_key = 'pricing-db-idempotency-001';
    raise exception 'Stored pricing quote was mutable';
  exception when sqlstate '55000' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Pricing quote mutation trigger did not fire'; end if;

  if has_function_privilege('authenticated',
       'public.store_generation_pricing_quote(uuid,uuid,text,text,text,text,text,uuid,uuid,jsonb,timestamp with time zone)', 'EXECUTE') then
    raise exception 'Authenticated role unexpectedly can persist pricing quotes';
  end if;

  if has_table_privilege('service_role', 'public.generation_pricing_quotes', 'UPDATE')
     or has_table_privilege('service_role', 'public.generation_pricing_quotes', 'DELETE')
     or has_table_privilege('service_role', 'public.generation_pricing_quotes', 'TRUNCATE')
     or not has_table_privilege('service_role', 'public.generation_pricing_quotes', 'INSERT')
     or not has_table_privilege('service_role', 'public.generation_pricing_quotes', 'SELECT') then
    raise exception 'Pricing quote table grants do not enforce append-only access';
  end if;
end;
$pricing_quote_persistence_test$;



-- Provider costs are owner-bound, append-only, idempotent, and compared to an
-- optional server-authored per-job USD ceiling without changing user credits.
insert into public.generation_jobs(
  id, user_id, job_type, provider, model, idempotency_key, request_hash, pricing_snapshot
) values (
  '12121212-1212-4121-8121-121212121212',
  '11111111-1111-4111-8111-111111111111',
  'image_generation', 'cost-test-provider', 'cost-test-model',
  'provider-cost-test-job-001', repeat('f', 64),
  '{"maximum_provider_cost_usd":0.05,"pricing_version":"test-cost-v1"}'::jsonb
);

do $provider_cost_event_test$
declare
  v_first record;
  v_replay record;
  v_second record;
  v_unknown record;
  v_rejected boolean := false;
begin
  select * into v_first from public.record_generation_provider_cost(
    '12121212-1212-4121-8121-121212121212',
    '11111111-1111-4111-8111-111111111111',
    'provider-call-attempt-001',
    'cost-test-provider', 'cost-test-model', 'provider-usage-001',
    0.03, 'reported', 100, 20, 120, 'token',
    '{"billing_reference":"synthetic-test-001"}'::jsonb
  );
  if not v_first.created or v_first.cumulative_known_cost_usd <> 0.03
     or v_first.budget_limit_usd <> 0.05
     or v_first.budget_exceeded is distinct from false then
    raise exception 'First provider cost event or under-budget calculation failed';
  end if;

  select * into v_replay from public.record_generation_provider_cost(
    '12121212-1212-4121-8121-121212121212',
    '11111111-1111-4111-8111-111111111111',
    'provider-call-attempt-001',
    'cost-test-provider', 'cost-test-model', 'provider-usage-001',
    0.03, 'reported', 100, 20, 120, 'token',
    '{"billing_reference":"synthetic-test-001"}'::jsonb
  );
  if v_replay.created or v_replay.event_id <> v_first.event_id
     or v_replay.cumulative_known_cost_usd <> 0.03 then
    raise exception 'Provider cost event replay was not idempotent';
  end if;

  v_rejected := false;
  begin
    perform public.record_generation_provider_cost(
      '12121212-1212-4121-8121-121212121212',
      '11111111-1111-4111-8111-111111111111',
      'provider-call-attempt-001',
      'cost-test-provider', 'cost-test-model', 'provider-usage-001',
      0.04, 'reported', 100, 20, 120, 'token',
      '{"billing_reference":"synthetic-test-001"}'::jsonb
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Provider cost idempotency key accepted changed cost evidence';
  end if;

  select * into v_second from public.record_generation_provider_cost(
    '12121212-1212-4121-8121-121212121212',
    '11111111-1111-4111-8111-111111111111',
    'provider-call-attempt-002',
    'cost-test-provider', 'cost-test-model', 'provider-usage-002',
    0.03, 'estimated', 50, 10, 60, 'token', '{}'::jsonb
  );
  if not v_second.created or v_second.cumulative_known_cost_usd <> 0.06
     or v_second.budget_exceeded is distinct from true then
    raise exception 'Cumulative provider cost ceiling was not detected';
  end if;

  select * into v_unknown from public.record_generation_provider_cost(
    '12121212-1212-4121-8121-121212121212',
    '11111111-1111-4111-8111-111111111111',
    'provider-call-attempt-003',
    'cost-test-provider', 'cost-test-model', null,
    null, 'unknown', null, null, null, 'unknown',
    '{"reason":"provider did not return usage"}'::jsonb
  );
  if not v_unknown.created or v_unknown.cumulative_known_cost_usd <> 0.06
     or v_unknown.budget_exceeded is distinct from true then
    raise exception 'Unknown usage evidence corrupted known-cost over-budget status';
  end if;

  v_rejected := false;
  begin
    perform public.record_generation_provider_cost(
      '12121212-1212-4121-8121-121212121212',
      '22222222-2222-4222-8222-222222222222',
      'provider-foreign-owner-001',
      'cost-test-provider', 'cost-test-model', null,
      0.01, 'reported', null, null, null, 'request', '{}'::jsonb
    );
  exception when sqlstate '42501' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Provider cost event accepted a foreign job owner';
  end if;

  v_rejected := false;
  begin
    update public.generation_provider_cost_events
       set cost_usd = 999
     where job_id = '12121212-1212-4121-8121-121212121212';
    raise exception 'Provider cost events were mutable';
  exception when sqlstate '55000' then v_rejected := true;
  end;
  if not v_rejected then raise exception 'Provider cost append-only trigger did not fire'; end if;

  if has_function_privilege('authenticated',
       'public.record_generation_provider_cost(uuid,uuid,text,text,text,text,numeric,text,bigint,bigint,bigint,text,jsonb)', 'EXECUTE')
     or has_table_privilege('authenticated', 'public.generation_provider_cost_events', 'SELECT')
     or has_table_privilege('anon', 'public.generation_provider_cost_events', 'SELECT')
     or has_table_privilege('service_role', 'public.generation_provider_cost_events', 'INSERT')
     or has_table_privilege('service_role', 'public.generation_provider_cost_events', 'UPDATE')
     or has_table_privilege('service_role', 'public.generation_provider_cost_events', 'DELETE')
     or has_table_privilege('service_role', 'public.generation_provider_cost_events', 'TRUNCATE')
     or not has_table_privilege('service_role', 'public.generation_provider_cost_events', 'SELECT') then
    raise exception 'Provider cost event privileges are not least-privilege';
  end if;
end;
$provider_cost_event_test$;

select 'provider cost event audit checks passed' as result;

-- A reclaimed lease fences every stale worker mutation while preserving one provider operation.
do $stale_worker_fencing_test$
declare
  v_job_id uuid;
  v_hold_id uuid;
  v_claim_a record;
  v_claim_b record;
  v_journal_a record;
  v_journal_b record;
  v_stale_completed record;
  v_completed record;
  v_available bigint;
  v_reserved bigint;
  v_capture_count integer;
begin
  update public.generation_jobs
     set status = 'failed', last_error_code = 'fencing_test_isolation',
         lease_owner = null, lease_expires_at = null, heartbeat_at = null,
         completed_at = now(), updated_at = now()
   where status in ('queued', 'retry_wait')
      or (status = 'running' and lease_expires_at <= now());

  insert into auth.users(id)
  values ('33333333-3333-4333-8333-333333333333')
  on conflict (id) do nothing;
  insert into public.credit_wallets(user_id, available_credits, reserved_credits)
  values ('33333333-3333-4333-8333-333333333333', 100, 0)
  on conflict (user_id) do update
    set available_credits = 100, reserved_credits = 0;

  select job_id into v_job_id from public.create_generation_job_with_outbox(
    '33333333-3333-4333-8333-333333333333', null,
    'image_generation', 'fencing-provider', 'fencing-model',
    'stale-worker-fencing-001', repeat('f', 64),
    '{"prompt":"stale worker fencing integration"}'::jsonb, '{}'::jsonb
  );
  select hold_id into v_hold_id from public.reserve_job_credits(
    '33333333-3333-4333-8333-333333333333', v_job_id, 25,
    'stale-worker-fencing-reservation',
    '{"price_version":"test-v1","approved_maximum":25}'::jsonb
  );

  select * into v_claim_a
    from public.claim_next_generation_job('fencing-worker-a', 60);
  if v_claim_a.job_id is distinct from v_job_id then
    raise exception 'First fencing worker did not claim the fixture';
  end if;
  select * into v_journal_a
    from public.begin_generation_provider_operation(
      v_job_id, 'fencing-worker-a', 'fencing-provider', v_job_id::text
    );
  if not v_journal_a.created then
    raise exception 'First worker did not create the durable provider operation';
  end if;

  update public.generation_jobs
     set lease_expires_at = now() - interval '1 second'
   where id = v_job_id;

  select * into v_claim_b
    from public.claim_next_generation_job('fencing-worker-b', 60);
  if v_claim_b.job_id is distinct from v_job_id then
    raise exception 'Replacement worker did not reclaim the expired lease';
  end if;

  if public.heartbeat_generation_job(v_job_id, 'fencing-worker-a', 60)
     or public.retry_generation_job(v_job_id, 'fencing-worker-a', 'stale_retry', 1)
     or public.fail_generation_job(v_job_id, 'fencing-worker-a', 'stale_failure')
     or public.complete_generation_job(
       v_job_id, 'fencing-worker-a',
       '33333333-3333-4333-8333-333333333333/results/stale.png'
     ) then
    raise exception 'A stale worker mutated the reclaimed job';
  end if;

  if public.mark_generation_provider_operation_accepted(
       v_job_id, 'fencing-worker-a', 'stale-provider-request'
     )
     or public.mark_generation_provider_operation_unknown(
       v_job_id, 'fencing-worker-a', 'stale_response_lost'
     )
     or public.mark_generation_provider_operation_result_received(
       v_job_id, 'fencing-worker-a', 'stale-provider-request'
     ) then
    raise exception 'A stale worker mutated the provider operation journal';
  end if;

  select * into v_journal_b
    from public.begin_generation_provider_operation(
      v_job_id, 'fencing-worker-b', 'fencing-provider', v_job_id::text
    );
  if v_journal_b.created or v_journal_b.operation_id <> v_journal_a.operation_id
     or v_journal_b.operation_state <> 'submitting' then
    raise exception 'Reclaimed worker did not recover the original provider operation';
  end if;

  if not public.mark_generation_provider_operation_result_received(
       v_job_id, 'fencing-worker-b', 'provider-result-after-reclaim'
     ) then
    raise exception 'Replacement worker could not record the recovered provider result';
  end if;

  select * into v_stale_completed
    from public.complete_credited_generation_job(
      v_job_id, 'fencing-worker-a',
      '33333333-3333-4333-8333-333333333333/results/final.png', repeat('c', 64)
  );
  if v_stale_completed.completed then
    raise exception 'Stale worker completed a job after its lease was reclaimed';
  end if;

  select * into v_completed
    from public.complete_credited_generation_job(
      v_job_id, 'fencing-worker-b',
      '33333333-3333-4333-8333-333333333333/results/final.png', repeat('c', 64)
  );
  if not v_completed.completed or v_completed.replayed then
    raise exception 'Replacement worker could not atomically complete the credited job';
  end if;

  select available_credits, reserved_credits into v_available, v_reserved
    from public.credit_wallets
   where user_id = '33333333-3333-4333-8333-333333333333';
  if v_available <> 75 or v_reserved <> 0 then
    raise exception 'Reclaimed job completion did not capture the reservation exactly once';
  end if;

  select count(*) into v_capture_count
    from public.credit_ledger
   where hold_id = v_hold_id and operation_type = 'capture';
  if v_capture_count <> 1 then
    raise exception 'Reclaimed job produced duplicate or missing credit capture';
  end if;

  select * into v_stale_completed
    from public.complete_credited_generation_job(
      v_job_id, 'fencing-worker-a',
      '33333333-3333-4333-8333-333333333333/results/final.png', repeat('c', 64)
  );
  if not v_stale_completed.completed or not v_stale_completed.replayed then
    raise exception 'Exact completion replay was not recognized as a harmless idempotent replay';
  end if;
  select count(*) into v_capture_count
    from public.credit_ledger
   where hold_id = v_hold_id and operation_type = 'capture';
  if v_capture_count <> 1 then
    raise exception 'Exact stale completion replay captured credits twice';
  end if;
end;
$stale_worker_fencing_test$;

select 'stale worker fencing checks passed' as result;


-- Every terminal worker path releases held credits exactly once.
do $terminal_worker_credit_release_test$
declare
  v_fail_job uuid;
  v_retry_job uuid;
  v_expired_job uuid;
  v_hold_id uuid;
  v_claim record;
  v_available bigint;
  v_reserved bigint;
  v_released_count integer;
begin
  update public.generation_jobs
     set status = 'failed', lease_owner = null, lease_expires_at = null,
         heartbeat_at = null, completed_at = now(), updated_at = now()
   where status in ('queued', 'retry_wait');

  select job_id into v_fail_job from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'release-test-provider', 'release-test-model',
    'terminal-release-fail-001', repeat('a', 64), '{}'::jsonb, '{}'::jsonb
  );
  select job_id into v_retry_job from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'release-test-provider', 'release-test-model',
    'terminal-release-retry-001', repeat('b', 64), '{}'::jsonb, '{}'::jsonb
  );
  select job_id into v_expired_job from public.create_generation_job_with_outbox(
    '11111111-1111-4111-8111-111111111111', null,
    'image_generation', 'release-test-provider', 'release-test-model',
    'terminal-release-expired-001', repeat('c', 64), '{}'::jsonb, '{}'::jsonb
  );

  select hold_id into v_hold_id from public.reserve_job_credits(
    '11111111-1111-4111-8111-111111111111', v_fail_job, 5,
    'terminal-release-fail-operation',
    '{"price_version":"test-v1","approved_maximum":5}'::jsonb
  );
  select hold_id into v_hold_id from public.reserve_job_credits(
    '11111111-1111-4111-8111-111111111111', v_retry_job, 7,
    'terminal-release-retry-operation',
    '{"price_version":"test-v1","approved_maximum":7}'::jsonb
  );
  select hold_id into v_hold_id from public.reserve_job_credits(
    '11111111-1111-4111-8111-111111111111', v_expired_job, 9,
    'terminal-release-expired-operation',
    '{"price_version":"test-v1","approved_maximum":9}'::jsonb
  );

  update public.generation_jobs
     set status = 'running', attempt_count = 1, lease_owner = 'terminal-worker-a',
         lease_expires_at = now() + interval '60 seconds',
         heartbeat_at = now(), updated_at = now()
   where id = v_fail_job;
  if not public.fail_generation_job(v_fail_job, 'terminal-worker-a', 'provider_rejected') then
    raise exception 'Active worker could not fail the credited job';
  end if;

  update public.generation_jobs
     set status = 'running', attempt_count = max_attempts, lease_owner = 'terminal-worker-b',
         lease_expires_at = now() + interval '60 seconds',
         heartbeat_at = now(), updated_at = now()
   where id = v_retry_job;
  if not public.retry_generation_job(v_retry_job, 'terminal-worker-b', 'retry_exhausted', 30) then
    raise exception 'Exhausted retry did not transition the credited job';
  end if;

  update public.generation_jobs
     set status = 'running', attempt_count = max_attempts, lease_owner = 'worker-that-crashed',
         lease_expires_at = now() - interval '1 second',
         heartbeat_at = now() - interval '2 seconds', updated_at = now()
   where id = v_expired_job;
  select * into v_claim from public.claim_next_generation_job('replacement-worker', 60);
  if v_claim.job_id is not null then
    raise exception 'Expired exhausted job was incorrectly reclaimed for another attempt';
  end if;

  if (select status from public.generation_jobs where id = v_fail_job) <> 'failed'
     or (select status from public.generation_jobs where id = v_retry_job) <> 'failed'
     or (select status from public.generation_jobs where id = v_expired_job) <> 'failed' then
    raise exception 'A terminal worker path did not leave its job failed';
  end if;

  select available_credits, reserved_credits into v_available, v_reserved
    from public.credit_wallets
   where user_id = '11111111-1111-4111-8111-111111111111';
  if v_available <> 100 or v_reserved <> 0 then
    raise exception 'Terminal worker paths did not restore the exact reserved credit balance';
  end if;

  select count(*) into v_released_count
    from public.credit_holds h
    join public.credit_ledger l on l.hold_id = h.id
   where h.job_id in (v_fail_job, v_retry_job, v_expired_job)
     and h.status = 'released'
     and l.operation_type = 'release';
  if v_released_count <> 3 then
    raise exception 'Expected exactly one release ledger entry per terminal credited job';
  end if;
end;
$terminal_worker_credit_release_test$;

select 'terminal worker credit release checks passed' as result;

