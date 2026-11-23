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
as $folder$ 
  select case
    when position('/' in trim(both '/' from object_name)) = 0 then array[]::text[]
    else (string_to_array(trim(both '/' from object_name), '/'))[1:array_length(string_to_array(trim(both '/' from object_name), '/'), 1) - 1]
  end
$folder$;

create or replace function storage.extension(object_name text)
returns text
language sql immutable
as $ext$ select lower(split_part(object_name, '.', array_length(string_to_array(object_name, '.'), 1))) $ext$;

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
\ir ../migrations/0025_provider_cost_budget_admission.sql
\ir ../migrations/0026_global_provider_budget_reservations.sql
\ir ../migrations/0027_site_visit_analytics.sql
\ir ../migrations/0028_site_visit_admin_analytics.sql
\ir ../migrations/0029_ai_request_admission.sql
\ir ../migrations/0030_credit_wallet_snapshot.sql

\ir ../migrations/0046_admin_credit_ledger_read.sql

do $admin_credit_ledger_privileges_test$
begin
  if not has_function_privilege('service_role',
       'public.list_admin_credit_ledger(uuid,timestamptz,bigint,integer)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.list_admin_credit_ledger(uuid,timestamptz,bigint,integer)', 'EXECUTE')
     or has_function_privilege('anon',
       'public.list_admin_credit_ledger(uuid,timestamptz,bigint,integer)', 'EXECUTE') then
    raise exception 'Admin credit ledger RPC privileges are not service-role-only';
  end if;
  if (select count(*) from public.list_admin_credit_ledger(
        '11111111-1111-4111-8111-111111111111', null, null, 50
      )) <> 0 then
    raise exception 'Unexpected fixture rows in fresh admin credit ledger';
  end if;
  begin
    perform * from public.list_admin_credit_ledger(
      '11111111-1111-4111-8111-111111111111', null, 1, 50
    );
    raise exception 'Partial keyset cursor was unexpectedly accepted';
  exception when invalid_parameter_value then
    null;
  end;
end;
$admin_credit_ledger_privileges_test$;


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
    ('11111111-1111-4111-8111-111111111111', 90, 10),
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
  v_admitted boolean;
begin
  -- Every synthetic billable operation must first obtain its durable reserve.
  perform public.configure_provider_budget_policy(1.00, 1.00);
  update public.generation_jobs
     set status = 'running', lease_owner = 'cost-test-worker',
         lease_expires_at = now() + interval '120 seconds',
         heartbeat_at = now(), updated_at = now()
   where id = '12121212-1212-4121-8121-121212121212';
  select public.authorize_generation_provider_operation(
    '12121212-1212-4121-8121-121212121212', 'cost-test-worker'
  ) into v_admitted;
  if v_admitted is distinct from true then
    raise exception 'Provider cost fixture could not reserve its maximum cost';
  end if;

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

  -- Crossing the internal ceiling must never erase or reject a real provider
  -- charge: preserve the actual evidence and flag the overrun for operators.
  if not exists (
    select 1 from public.generation_provider_cost_events
     where job_id = '12121212-1212-4121-8121-121212121212'
       and operation_key = 'provider-call-attempt-002'
       and cost_usd = 0.03
       and cost_source = 'estimated'
       and cumulative_known_cost_usd = 0.06
       and budget_limit_usd = 0.05
       and budget_exceeded is true
  ) then
    raise exception 'Over-budget provider charge was not retained as actual cost evidence';
  end if;

  -- A provider usage ID is globally unique per provider. A second operation
  -- key must not duplicate or silently reclassify the same billing record.
  v_rejected := false;
  begin
    perform public.record_generation_provider_cost(
      '12121212-1212-4121-8121-121212121212',
      '11111111-1111-4111-8111-111111111111',
      'provider-call-attempt-duplicate-usage',
      'cost-test-provider', 'cost-test-model', 'provider-usage-001',
      0.03, 'reported', 100, 20, 120, 'token',
      '{"billing_reference":"synthetic-test-001"}'::jsonb
    );
  exception when unique_violation then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Duplicate provider usage ID was accepted under another operation key';
  end if;
  if (select count(*) from public.generation_provider_cost_events
       where provider = 'cost-test-provider'
         and provider_usage_id = 'provider-usage-001') <> 1 then
    raise exception 'Duplicate provider usage ID created more than one cost event';
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
  if not public.resolve_generation_provider_reservation(
       '12121212-1212-4121-8121-121212121212',
       'provider-cost-event-test-reconcile', 'settle_known_cost', 0.01,
       'Synthetic test invoice resolves unknown provider usage.'
     ) then
    raise exception 'Provider cost test reservation could not be reconciled';
  end if;
  perform public.configure_provider_budget_policy(null, null);
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
  -- Preserve the separate 10-credit held fixture created by the schema test above.
  if v_available <> 90 or v_reserved <> 10 then
    raise exception 'Terminal worker paths did not restore their reservations without changing the unrelated held fixture';
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



-- Provider budget admission requires a live lease, explicit USD ceiling, and
-- complete known costs below the ceiling. Missing/unknown/exhausted evidence fails closed.
do $provider_budget_admission_test$
declare
  v_job_id uuid := '13131313-1313-4131-8131-131313131313';
  v_unknown_job_id uuid := '14141414-1414-4141-8141-141414141414';
  v_allowed boolean;
begin
  -- The replacement global gate is disabled by default; enable bounded test
  -- policy values explicitly for this isolated fixture.
  perform public.configure_provider_budget_policy(1.00, 1.00);

  insert into public.generation_jobs(
    id, user_id, job_type, provider, model, idempotency_key,
    request_hash, pricing_snapshot
  ) values (
    v_job_id, '11111111-1111-4111-8111-111111111111',
    'image_generation', 'budget-test-provider', 'budget-test-model',
    'provider-budget-admission-001', repeat('d', 64),
    '{"maximum_provider_cost_usd":0.05,"pricing_version":"budget-test-v1"}'::jsonb
  );

  update public.generation_jobs
     set status = 'running', lease_owner = 'budget-test-worker',
         lease_expires_at = now() + interval '120 seconds',
         heartbeat_at = now(), updated_at = now()
   where id = v_job_id;

  select public.authorize_generation_provider_operation(v_job_id, 'budget-test-worker')
    into v_allowed;
  if v_allowed is distinct from true then
    raise exception 'Under-budget job with a valid lease was not admitted';
  end if;

  perform public.record_generation_provider_cost(
    v_job_id, '11111111-1111-4111-8111-111111111111',
    'budget-test-operation-001', 'budget-test-provider', 'budget-test-model',
    'budget-test-usage-001', 0.05, 'reported', 10, 10, 20, 'token', '{}'::jsonb
  );
  select public.authorize_generation_provider_operation(v_job_id, 'budget-test-worker')
    into v_allowed;
  if v_allowed is distinct from false then
    raise exception 'Budget gate admitted a new call after reaching the USD ceiling';
  end if;

  insert into public.generation_jobs(
    id, user_id, job_type, provider, model, idempotency_key,
    request_hash, pricing_snapshot
  ) values (
    v_unknown_job_id, '11111111-1111-4111-8111-111111111111',
    'image_generation', 'budget-test-provider', 'budget-test-model',
    'provider-budget-unknown-001', repeat('e', 64),
    '{"maximum_provider_cost_usd":0.10,"pricing_version":"budget-test-v1"}'::jsonb
  );
  update public.generation_jobs
     set status = 'running', lease_owner = 'budget-test-worker',
         lease_expires_at = now() + interval '120 seconds',
         heartbeat_at = now(), updated_at = now()
   where id = v_unknown_job_id;
  select public.authorize_generation_provider_operation(v_unknown_job_id, 'budget-test-worker')
    into v_allowed;
  if v_allowed is distinct from true then
    raise exception 'Unknown-cost fixture could not create its provider reservation';
  end if;
  perform public.record_generation_provider_cost(
    v_unknown_job_id, '11111111-1111-4111-8111-111111111111',
    'budget-test-operation-unknown', 'budget-test-provider', 'budget-test-model',
    null, null, 'unknown', null, null, null, 'unknown',
    '{"reason":"provider usage unavailable"}'::jsonb
  );
  select public.authorize_generation_provider_operation(v_unknown_job_id, 'budget-test-worker')
    into v_allowed;
  if v_allowed is distinct from false then
    raise exception 'Budget gate admitted a new call while prior provider cost was unknown';
  end if;

  update public.generation_jobs
     set lease_expires_at = now() - interval '1 second'
   where id = v_job_id;
  select public.authorize_generation_provider_operation(v_job_id, 'budget-test-worker')
    into v_allowed;
  if v_allowed is distinct from false then
    raise exception 'Budget gate admitted a stale worker lease';
  end if;

  if has_function_privilege('authenticated',
       'public.authorize_generation_provider_operation(uuid,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.authorize_generation_provider_operation(uuid,text)', 'EXECUTE') then
    raise exception 'Provider budget admission RPC privileges are not least-privilege';
  end if;

  -- Reconcile the deliberately unknown fixture against a known test invoice so
  -- the following global-budget scenario starts without leftover exposure.
  if not public.resolve_generation_provider_reservation(
       v_unknown_job_id, 'legacy-budget-test-reconcile', 'settle_known_cost', 0.01,
       'Test invoice confirms the provider operation charge.'
     ) then
    raise exception 'Could not reconcile the legacy unknown-cost test fixture';
  end if;
  perform public.configure_provider_budget_policy(null, null);
end;
$provider_budget_admission_test$;

select 'provider budget admission checks passed' as result;


-- Global provider budgets serialize admission across distinct jobs and retain
-- ambiguous reservations across worker lease expiry and UTC day boundaries.
do $global_provider_budget_reservations_test$
declare
  v_job_a uuid := '26262626-2626-4262-8262-262626262626';
  v_job_b uuid := '27272727-2727-4272-8272-272727272727';
  v_job_unknown uuid := '28282828-2828-4282-8282-282828282828';
  v_job_next_day uuid := '29292929-2929-4292-8292-292929292929';
  v_allowed boolean;
  v_count integer;
  v_status text;
  v_reserved numeric(20,10);
begin
  -- No operator policy means no billable operation is admitted.
  perform public.configure_provider_budget_policy(null, null);

  insert into public.generation_jobs(
    id, user_id, job_type, provider, model, idempotency_key,
    request_hash, pricing_snapshot
  ) values
    (v_job_a, '11111111-1111-4111-8111-111111111111',
     'image_generation', 'global-budget-provider', 'global-budget-model',
     'global-budget-job-a-001', repeat('a', 64),
     '{"maximum_provider_cost_usd":"0.10"}'::jsonb),
    (v_job_b, '11111111-1111-4111-8111-111111111111',
     'image_generation', 'global-budget-provider', 'global-budget-model',
     'global-budget-job-b-001', repeat('b', 64),
     '{"maximum_provider_cost_usd":"0.10"}'::jsonb),
    (v_job_unknown, '11111111-1111-4111-8111-111111111111',
     'image_generation', 'global-budget-provider', 'global-budget-model',
     'global-budget-job-unknown-001', repeat('c', 64),
     '{"maximum_provider_cost_usd":"0.05"}'::jsonb),
    (v_job_next_day, '11111111-1111-4111-8111-111111111111',
     'image_generation', 'global-budget-provider', 'global-budget-model',
     'global-budget-job-next-day-001', repeat('d', 64),
     '{"maximum_provider_cost_usd":"0.05"}'::jsonb);

  update public.generation_jobs
     set status = 'running', lease_owner = 'global-budget-worker',
         lease_expires_at = now() + interval '120 seconds',
         heartbeat_at = now(), updated_at = now()
   where id in (v_job_a, v_job_b, v_job_unknown, v_job_next_day);

  select public.authorize_generation_provider_operation(v_job_a, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from false then
    raise exception 'Disabled global provider budget policy admitted a billable call';
  end if;

  -- Daily limit 0.40 USD and outstanding exposure limit 0.15 USD.
  if not public.configure_provider_budget_policy(0.40, 0.15) then
    raise exception 'Operator could not configure the global provider budget policy';
  end if;

  select public.authorize_generation_provider_operation(v_job_a, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from true then
    raise exception 'First job was not admitted under available global budget';
  end if;

  -- Idempotent re-admission for the same job reuses one reservation.
  select public.authorize_generation_provider_operation(v_job_a, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from true then
    raise exception 'Repeated admission for the same job was not idempotent';
  end if;
  select count(*) into v_count
    from public.generation_provider_cost_reservations
   where job_id = v_job_a;
  if v_count <> 1 then
    raise exception 'Repeated admission created duplicate provider reservations';
  end if;

  -- A different job cannot overbook the shared outstanding-exposure cap.
  select public.authorize_generation_provider_operation(v_job_b, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from false then
    raise exception 'Second distinct job overbooked the global exposure cap';
  end if;

  -- Known usage settles the reserve and actual spend replaces estimated exposure.
  -- Insert immutable known-cost evidence dated in the prior UTC day.
  -- The ledger trigger still settles the reservation; this also lets the test
  -- prove that old spend rolls out while outstanding reserves remain active.
  insert into public.generation_provider_cost_events(
    user_id, job_id, operation_key, provider, model, provider_usage_id,
    cost_usd, cost_source, input_units, output_units, total_units, unit_kind,
    metadata, budget_limit_usd, cumulative_known_cost_usd, budget_exceeded, created_at
  ) values (
    '11111111-1111-4111-8111-111111111111', v_job_a,
    'global-budget-known-operation-001', 'global-budget-provider', 'global-budget-model',
    'global-budget-usage-known-001', 0.04, 'reported', 10, 10, 20, 'token',
    '{}'::jsonb, 0.10, 0.04, false,
    (date_trunc('day', now() at time zone 'UTC') at time zone 'UTC') - interval '1 second'
  );
  select status into v_status
    from public.generation_provider_cost_reservations where job_id = v_job_a;
  if v_status <> 'settled' then
    raise exception 'Known provider cost did not settle its reservation';
  end if;

  select public.authorize_generation_provider_operation(v_job_b, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from true then
    raise exception 'Second job was not admitted after the first reserve settled';
  end if;

  -- Unknown usage keeps the full reservation; it is never treated as zero.
  select public.authorize_generation_provider_operation(v_job_unknown, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from true then
    raise exception 'Unknown-cost fixture could not reserve remaining exposure';
  end if;
  perform public.record_generation_provider_cost(
    v_job_unknown, '11111111-1111-4111-8111-111111111111',
    'global-budget-unknown-operation-001', 'global-budget-provider', 'global-budget-model',
    null, null, 'unknown', null, null, null, 'unknown',
    '{"reason":"provider usage unavailable"}'::jsonb
  );
  select status, reserved_cost_usd into v_status, v_reserved
    from public.generation_provider_cost_reservations
   where job_id = v_job_unknown;
  if v_status <> 'unknown' or v_reserved <> 0.05 then
    raise exception 'Unknown provider cost released or reduced its reservation';
  end if;

  -- Expiring the worker lease does not release uncertain provider exposure.
  update public.generation_jobs
     set lease_expires_at = now() - interval '1 second'
   where id = v_job_unknown;
  select public.authorize_generation_provider_operation(v_job_unknown, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from false then
    raise exception 'Expired worker lease was admitted';
  end if;
  select status into v_status
    from public.generation_provider_cost_reservations
   where job_id = v_job_unknown;
  if v_status <> 'unknown' then
    raise exception 'Worker lease expiry incorrectly released an unknown-cost reservation';
  end if;

  -- A new UTC day resets daily spend, but outstanding reservations from the
  -- previous day still count against the concurrent exposure ceiling.
  update public.generation_provider_cost_reservations
     set created_at = now() - interval '1 day'
   where job_id in (v_job_b, v_job_unknown);

  if not public.configure_provider_budget_policy(0.32, 0.30) then
    raise exception 'Could not configure the daily-limit rejection assertion';
  end if;
  select public.authorize_generation_provider_operation(v_job_next_day, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from false then
    raise exception 'Admission exceeded the configured daily budget';
  end if;

  if not public.configure_provider_budget_policy(0.33, 0.30) then
    raise exception 'Could not adjust test policy for UTC rollover assertion';
  end if;
  select public.authorize_generation_provider_operation(v_job_next_day, 'global-budget-worker')
    into v_allowed;
  if v_allowed is distinct from true then
    raise exception 'Previous-day known spend incorrectly consumed the new UTC daily budget';
  end if;

  -- Reservations created before midnight remain in the exposure calculation.
  if (select coalesce(sum(reserved_cost_usd), 0)
        from public.generation_provider_cost_reservations
       where status in ('reserved', 'unknown')) < 0.15 then
    raise exception 'Outstanding prior-day reservations disappeared at UTC rollover';
  end if;

  -- Operator reconciliation is explicit and idempotent: a verified no-charge
  -- result releases only its own reserve; a known charge appends ledger evidence.
  if not public.resolve_generation_provider_reservation(
       v_job_unknown, 'global-no-charge-001', 'release_no_charge', null,
       'Provider invoice confirms no charge.'
     ) then
    raise exception 'Operator could not release a verified no-charge reservation';
  end if;
  select status into v_status
    from public.generation_provider_cost_reservations
   where job_id = v_job_unknown;
  if v_status <> 'released' then
    raise exception 'Verified no-charge reconciliation did not release the reserve';
  end if;

  if not public.resolve_generation_provider_reservation(
       v_job_next_day, 'global-known-reconcile-001', 'settle_known_cost', 0.02,
       'Provider billing record confirms this operation cost.'
     ) then
    raise exception 'Operator could not settle a verified provider charge';
  end if;
  select status into v_status
    from public.generation_provider_cost_reservations
   where job_id = v_job_next_day;
  if v_status <> 'settled' then
    raise exception 'Known-cost reconciliation did not settle the reserve';
  end if;
  if not public.resolve_generation_provider_reservation(
       v_job_next_day, 'global-known-reconcile-001', 'settle_known_cost', 0.02,
       'Provider billing record confirms this operation cost.'
     ) then
    raise exception 'Exact operator reconciliation replay was not idempotent';
  end if;
  select count(*) into v_count
    from public.generation_provider_cost_events
   where job_id = v_job_next_day
     and operation_key = 'provider-reconciliation:global-known-reconcile-001';
  if v_count <> 1 then
    raise exception 'Operator reconciliation replay duplicated provider cost evidence';
  end if;

  -- The B fixture was admitted but deliberately never submitted to a provider.
  if not public.resolve_generation_provider_reservation(
       v_job_b, 'global-budget-b-cleanup-001', 'release_no_charge', null,
       'Integration fixture was never submitted to a provider.'
     ) then
    raise exception 'Could not release the never-submitted integration fixture';
  end if;

  if has_function_privilege('authenticated',
       'public.configure_provider_budget_policy(numeric,numeric)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.configure_provider_budget_policy(numeric,numeric)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.resolve_generation_provider_reservation(uuid,text,text,numeric,text)', 'EXECUTE') then
    raise exception 'Global provider budget operator RPC privileges are not least-privilege';
  end if;

  -- Leave the disposable test database fail-closed after this test block.
  perform public.configure_provider_budget_policy(null, null);
end;
$global_provider_budget_reservations_test$;

select 'global provider budget reservation checks passed' as result;


do $ai_request_admission_test$
declare
  v_user uuid := gen_random_uuid();
  v_other_user uuid := gen_random_uuid();
  v_global_user uuid := gen_random_uuid();
  v_first uuid := gen_random_uuid();
  v_second uuid := gen_random_uuid();
  v_third uuid := gen_random_uuid();
  v_other_request uuid := gen_random_uuid();
  v_result jsonb;
begin
  v_result := public.reserve_ai_request(v_user, v_first, 'chat', 2, 1);
  if v_result->>'admitted' <> 'true' then
    raise exception 'first AI request was not admitted';
  end if;

  v_result := public.reserve_ai_request(v_user, v_second, 'prompts', 2, 1);
  if v_result->>'admitted' <> 'false'
     or v_result->>'reason' <> 'concurrency_limited' then
    raise exception 'per-user concurrent AI limit was not enforced';
  end if;

  if not public.finish_ai_request(v_user, v_first, 'completed') then
    raise exception 'could not finalize admitted AI request';
  end if;

  v_result := public.reserve_ai_request(v_user, v_second, 'prompts', 2, 1);
  if v_result->>'admitted' <> 'true' then
    raise exception 'released concurrency slot did not admit next request';
  end if;

  v_result := public.reserve_ai_request(v_user, v_third, 'chat', 2, 1);
  if v_result->>'admitted' <> 'false'
     or v_result->>'reason' <> 'rate_limited' then
    raise exception 'per-minute AI request limit was not enforced';
  end if;

  v_result := public.reserve_ai_request(v_other_user, v_other_request, 'chat', 2, 1);
  if v_result->>'admitted' <> 'true' then
    raise exception 'one user''s rate limit incorrectly affected another user';
  end if;

  v_result := public.reserve_ai_request(
    v_global_user, gen_random_uuid(), 'chat', 2, 1, 1
  );
  if v_result->>'admitted' <> 'false'
     or v_result->>'reason' <> 'global_concurrency_limited' then
    raise exception 'global AI concurrency limit was not enforced across accounts';
  end if;

  if not public.finish_ai_request(v_user, v_second, 'released') then
    raise exception 'could not release failed AI request reservation';
  end if;
  if not public.finish_ai_request(v_other_user, v_other_request, 'released') then
    raise exception 'could not release isolated AI request reservation';
  end if;

  if has_function_privilege('authenticated',
       'public.reserve_ai_request(uuid,uuid,text,integer,integer,integer)', 'EXECUTE')
     or has_function_privilege('anon',
       'public.finish_ai_request(uuid,uuid,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.reserve_ai_request(uuid,uuid,text,integer,integer,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.finish_ai_request(uuid,uuid,text)', 'EXECUTE')
     or has_table_privilege('authenticated',
       'public.ai_request_admission_reservations', 'SELECT')
     or has_table_privilege('anon',
       'public.ai_request_admission_windows', 'SELECT') then
    raise exception 'AI admission storage/RPC privileges are not least-privilege';
  end if;
end;
$ai_request_admission_test$;

select 'distributed AI admission checks passed' as result;


\ir ../migrations/0031_credit_lots_and_allocations.sql
\ir ../migrations/0032_lot_aware_credit_lifecycle.sql
\ir ../migrations/0033_entitlement_policy_and_wallet_reconciliation.sql
\ir ../migrations/0034_paginated_wallet_reconciliation.sql
\ir ../migrations/0035_admin_audit_journal.sql
\ir ../migrations/0036_admin_audit_keyset_pagination.sql
\ir ../migrations/0037_finance_authorization_registry.sql
\ir ../migrations/0038_finance_role_registry_rpcs.sql
\ir ../migrations/0039_finance_role_self_assignment_guard.sql
\ir ../migrations/0040_finance_role_duplicate_grant_guard.sql
\ir ../migrations/0041_require_scoped_expiring_finance_roles.sql
\ir ../migrations/0042_finance_operation_request_storage.sql
\ir ../migrations/0043_finance_operation_request_rpcs.sql
\ir ../migrations/0044_finance_operation_request_queue.sql
\ir ../migrations/0045_finance_operation_request_event_read.sql

do $credit_entitlement_policy_test$
declare
  v_user uuid := gen_random_uuid();
  v_first record;
  v_replay record;
  v_after_revision record;
  v_lot_count integer;
begin
  if has_function_privilege('authenticated',
       'public.grant_user_credit_entitlement(uuid,text,text,text,jsonb)', 'EXECUTE')
     or has_table_privilege('service_role', 'public.credit_entitlement_policies', 'INSERT')
     or has_table_privilege('service_role', 'public.credit_entitlement_policies', 'UPDATE')
     or has_table_privilege('service_role', 'public.credit_entitlement_events', 'INSERT') then
    raise exception 'Entitlement policy or event storage has excessive runtime privileges';
  end if;
  insert into auth.users(id) values (v_user);
  insert into public.credit_entitlement_policies(
    policy_code, policy_version, lot_type, amount, expires_in_seconds, enabled
  ) values ('test_free_cycle', 1, 'free', null, 3600, false);

  begin
    perform * from public.grant_user_credit_entitlement(
      v_user, 'test_free_cycle', 'event-key-0001', 'test-source-0001', '{}'::jsonb
    );
    raise exception 'Disabled/unconfigured entitlement policy unexpectedly granted credits';
  exception when sqlstate '55000' then
    null;
  end;

  update public.credit_entitlement_policies
     set amount = 12, enabled = true
   where policy_code = 'test_free_cycle' and policy_version = 1;

  select * into v_first from public.grant_user_credit_entitlement(
    v_user, 'test_free_cycle', 'event-key-0001', 'test-source-0001', '{"reason":"test"}'::jsonb
  );
  select * into v_replay from public.grant_user_credit_entitlement(
    v_user, 'test_free_cycle', 'event-key-0001', 'test-source-0001', '{"reason":"test"}'::jsonb
  );
  if v_first.replayed or not v_replay.replayed or v_first.available_credits <> 12
     or v_replay.available_credits <> 12 then
    raise exception 'Entitlement grant replay was not idempotent';
  end if;

  insert into public.credit_entitlement_policies(
    policy_code, policy_version, lot_type, amount, expires_in_seconds, enabled
  ) values ('test_free_cycle', 2, 'free', 99, 3600, true);
  select * into v_after_revision from public.grant_user_credit_entitlement(
    v_user, 'test_free_cycle', 'event-key-0001', 'test-source-0001', '{"reason":"test"}'::jsonb
  );
  select count(*) into v_lot_count from public.credit_lots where user_id = v_user;
  if not v_after_revision.replayed or v_after_revision.available_credits <> 12
     or v_lot_count <> 1 then
    raise exception 'Policy revision duplicated a previously processed entitlement event';
  end if;
end;
$credit_entitlement_policy_test$;

select 'credit entitlement policy and replay checks passed' as result;


do $credit_wallet_snapshot_test$
declare
  v_user uuid := gen_random_uuid();
  v_empty_user uuid := gen_random_uuid();
  v_zero_wallet_user uuid := gen_random_uuid();
  v_ledger_only_user uuid := gen_random_uuid();
  v_snapshot jsonb;
  v_audit record;
  v_job_one uuid;
  v_job_two uuid;
  v_hold_one uuid;
  v_hold_two uuid;
  v_allocation_one uuid;
  v_allocation_two uuid;
  v_extra_job uuid;
  v_extra_hold uuid;
  v_extra_allocation uuid;
  v_extra_lot uuid;
  v_legacy_lot uuid;
begin
  insert into auth.users(id) values
    (v_user), (v_empty_user), (v_zero_wallet_user), (v_ledger_only_user);
  insert into public.credit_wallets(user_id, available_credits, reserved_credits)
  values (v_user, 125, 0);
  insert into public.credit_lots(
    user_id, lot_type, source_reference, idempotency_key,
    granted_credits, available_credits, reserved_credits
  ) values (
    v_user, 'legacy', 'test-source-001', 'test-lot-0001',
    125, 125, 0
  );
  insert into public.credit_ledger(
    user_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    v_user, 'grant', 'grant:test-wallet-001',
    125, 0, 125, 0, '{"source":"integration_test"}'::jsonb
  );

  v_snapshot := public.get_credit_wallet_snapshot(v_user, 50);
  select * into v_audit
    from public.audit_credit_wallet_reconciliation(v_user, 10);
  if not found or not v_audit.healthy or not v_audit.wallet_lots_match
     or not v_audit.latest_ledger_matches then
    raise exception 'Healthy wallet failed read-only reconciliation';
  end if;

  update public.credit_lots set available_credits = 124 where user_id = v_user;
  select * into v_audit
    from public.audit_credit_wallet_reconciliation(v_user, 10);
  if not found or v_audit.healthy or v_audit.wallet_lots_match then
    raise exception 'Reconciliation did not detect lot/wallet drift';
  end if;
  update public.credit_lots set available_credits = 125 where user_id = v_user;

  -- Aggregate totals alone can conceal swapped/misassigned hold allocations.
  -- Keep user, wallet, lot and ledger totals constant while breaking each hold's
  -- own allocation amount; the detailed reconciliation must still detect drift.
  select job_id into v_job_one from public.create_generation_job_with_outbox(
    v_user, null, 'image_generation', 'audit-provider', 'audit-model',
    'audit-hold-job-one', repeat('a', 64), '{}'::jsonb, '{}'::jsonb
  );
  select hold_id into v_hold_one from public.reserve_job_credits(
    v_user, v_job_one, 5, 'audit-hold-key-001', '{}'::jsonb
  );
  select job_id into v_job_two from public.create_generation_job_with_outbox(
    v_user, null, 'image_generation', 'audit-provider', 'audit-model',
    'audit-hold-job-two', repeat('b', 64), '{}'::jsonb, '{}'::jsonb
  );
  select hold_id into v_hold_two from public.reserve_job_credits(
    v_user, v_job_two, 10, 'audit-hold-key-002', '{}'::jsonb
  );
  select id into v_allocation_one from public.credit_hold_allocations
   where hold_id = v_hold_one and status = 'held';
  select id into v_allocation_two from public.credit_hold_allocations
   where hold_id = v_hold_two and status = 'held';
  update public.credit_hold_allocations set amount = 10 where id = v_allocation_one;
  update public.credit_hold_allocations set amount = 5 where id = v_allocation_two;
  select * into v_audit from public.audit_credit_wallet_reconciliation(v_user, 10);
  if not found or v_audit.healthy or v_audit.allocations_match then
    raise exception 'Reconciliation missed per-hold allocation drift with matching aggregate totals';
  end if;
  update public.credit_hold_allocations set amount = 5 where id = v_allocation_one;
  update public.credit_hold_allocations set amount = 10 where id = v_allocation_two;
  select * into v_audit from public.audit_credit_wallet_reconciliation(v_user, 10);
  if not found or not v_audit.healthy or not v_audit.allocations_match then
    raise exception 'Reconciliation did not recover after per-hold allocations were restored';
  end if;

  -- Verify per-lot allocation totals independently: move one held allocation
  -- to another valid lot without changing its hold amount or aggregate totals.
  perform public.grant_user_credit_lot(
    v_user, 3, 'bonus', 'audit-extra-source', 'audit-extra-lot-001',
    now() + interval '1 day', '{}'::jsonb
  );
  select id into v_extra_lot from public.credit_lots
   where user_id = v_user and idempotency_key = 'audit-extra-lot-001';
  select id into v_legacy_lot from public.credit_lots
   where user_id = v_user and lot_type = 'legacy';
  select job_id into v_extra_job from public.create_generation_job_with_outbox(
    v_user, null, 'image_generation', 'audit-provider', 'audit-model',
    'audit-hold-job-extra', repeat('d', 64), '{}'::jsonb, '{}'::jsonb
  );
  select hold_id into v_extra_hold from public.reserve_job_credits(
    v_user, v_extra_job, 3, 'audit-hold-key-extra', '{}'::jsonb
  );
  select id into v_extra_allocation from public.credit_hold_allocations
   where hold_id = v_extra_hold and status = 'held' and lot_id = v_extra_lot;
  if v_extra_allocation is null then
    raise exception 'FIFO reservation did not select the earliest-expiring bonus lot';
  end if;
  update public.credit_hold_allocations set lot_id = v_legacy_lot
   where id = v_extra_allocation;
  select * into v_audit from public.audit_credit_wallet_reconciliation(v_user, 10);
  if not found or v_audit.healthy or v_audit.allocations_match then
    raise exception 'Reconciliation missed per-lot allocation drift with matching aggregate totals';
  end if;
  update public.credit_hold_allocations set lot_id = v_extra_lot
   where id = v_extra_allocation;
  select * into v_audit from public.audit_credit_wallet_reconciliation(v_user, 10);
  if not found or not v_audit.healthy or not v_audit.allocations_match then
    raise exception 'Reconciliation did not recover after per-lot allocations were restored';
  end if;

  -- A persisted zero-balance wallet without any journal entry is an anomaly,
  -- not an unrecorded "healthy" account. A user with only ledger rows must
  -- also appear in the reconciliation result instead of being silently skipped.
  insert into public.credit_wallets(user_id, available_credits, reserved_credits)
  values (v_zero_wallet_user, 0, 0);
  select * into v_audit
    from public.audit_credit_wallet_reconciliation(v_zero_wallet_user, 10);
  if not found or v_audit.healthy or v_audit.latest_ledger_matches then
    raise exception 'Zero wallet without a ledger entry was not flagged as an anomaly';
  end if;

  insert into public.credit_ledger(
    user_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    v_ledger_only_user, 'grant', 'grant:ledger-only-test',
    9, 0, 9, 0, '{"source":"reconciliation_test"}'::jsonb
  );
  select * into v_audit
    from public.audit_credit_wallet_reconciliation(v_ledger_only_user, 10);
  if not found or v_audit.healthy
     or v_audit.wallet_available <> 0
     or v_audit.latest_ledger_available <> 9
     or v_audit.latest_ledger_matches then
    raise exception 'Ledger-only user was omitted or not flagged for missing wallet projection';
  end if;

  if has_function_privilege('authenticated',
       'public.audit_credit_wallet_reconciliation(uuid,integer)', 'EXECUTE') then
    raise exception 'Authenticated role can invoke privileged wallet reconciliation';
  end if;

  if v_snapshot->>'user_id' <> v_user::text
     or v_snapshot->>'currency_unit' <> 'credit'
     or (v_snapshot->>'lot_count')::bigint <> 1
     or (v_snapshot->>'lot_available_total')::bigint <> 125
     or (v_snapshot->>'lot_reserved_total')::bigint <> 0
     or (v_snapshot->>'lots_truncated')::boolean
     or (v_snapshot->>'allocation_count')::bigint <> 0
     or (v_snapshot->>'allocations_truncated')::boolean
     or (v_snapshot->>'available_credits')::bigint <> 125
     or (v_snapshot->>'reserved_credits')::bigint <> 0
     or jsonb_array_length(v_snapshot->'ledger') <> 1
     or v_snapshot->'ledger'->0->>'operation_type' <> 'grant'
     or jsonb_array_length(v_snapshot->'lots') <> 1
     or v_snapshot->'lots'->0->>'lot_type' <> 'legacy'
     or jsonb_array_length(v_snapshot->'allocations') <> 0
     or v_snapshot ? 'quote_snapshot' then
    raise exception 'Wallet snapshot did not return the expected owner-scoped balances/history/lots';
  end if;

  v_snapshot := public.get_credit_wallet_snapshot(v_empty_user, 10);
  if (v_snapshot->>'available_credits')::bigint <> 0
     or (v_snapshot->>'reserved_credits')::bigint <> 0
     or jsonb_array_length(v_snapshot->'ledger') <> 0 then
    raise exception 'Missing wallet must return zero without creating or granting credits';
  end if;

  if not exists (
    select 1 from public.credit_lots
     where user_id = '33333333-3333-4333-8333-333333333333'
       and lot_type = 'legacy' and available_credits = 75
  ) then
    raise exception 'Existing wallet balance was not safely backfilled into a legacy lot';
  end if;

  if exists (
    select 1
      from public.credit_wallets w
      left join lateral (
        select coalesce(sum(l.available_credits), 0) as available,
               coalesce(sum(l.reserved_credits), 0) as reserved
          from public.credit_lots l where l.user_id = w.user_id
      ) lots on true
     where lots.available <> w.available_credits
        or lots.reserved <> w.reserved_credits
  ) then
    raise exception 'Backfilled credit lot totals do not reconcile to wallet balances';
  end if;

  if exists (
    select 1
      from public.credit_holds h
     where h.status = 'held'
       and not exists (
         select 1 from public.credit_hold_allocations a
          where a.hold_id = h.id and a.user_id = h.user_id
            and a.status = 'held'
       )
  ) then
    raise exception 'An active legacy hold is missing its lot allocation';
  end if;

  if not exists (
    select 1 from pg_constraint
     where conrelid = 'public.credit_lots'::regclass
       and conname = 'credit_lots_amounts_within_grant'
  ) or not exists (
    select 1 from pg_constraint
     where conrelid = 'public.credit_hold_allocations'::regclass
       and conname = 'credit_hold_allocations_hold_lot_unique'
  ) then
    raise exception 'Credit lot integrity constraints are missing';
  end if;

  if not has_function_privilege('service_role',
       'public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamp with time zone,jsonb)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.grant_user_credits(uuid,bigint,text,jsonb)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.reserve_job_credits(uuid,uuid,bigint,text,jsonb)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.release_job_credit_hold(uuid,uuid,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.create_credited_generation_job_with_outbox(uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.complete_credited_generation_job(uuid,text,text,text)', 'EXECUTE') then
    raise exception 'Lot-aware financial mutation RPCs are not enabled for the trusted service role';
  end if;
  if has_function_privilege('authenticated',
       'public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamp with time zone,jsonb)', 'EXECUTE')
     or has_function_privilege('anon',
       'public.grant_user_credit_lot(uuid,bigint,text,text,text,timestamp with time zone,jsonb)', 'EXECUTE') then
    raise exception 'Untrusted roles must not invoke credit lot grants';
  end if;

  if has_function_privilege('anon',
       'public.get_credit_wallet_snapshot(uuid,integer)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.get_credit_wallet_snapshot(uuid,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.get_credit_wallet_snapshot(uuid,integer)', 'EXECUTE') then
    raise exception 'Wallet snapshot RPC privileges are not least-privilege';
  end if;

  begin
    perform public.get_credit_wallet_snapshot(v_user, 101);
    raise exception 'Wallet history limit above 100 should be rejected';
  exception when sqlstate '22023' then
    null;
  end;
end;
$credit_wallet_snapshot_test$;

-- Source-aware grants, earliest-expiry-first reservations, capture, release and expiry.
do $credit_lot_lifecycle_test$
declare
  v_user uuid := '44444444-4444-4444-8444-444444444444';
  v_other uuid := '55555555-5555-4555-8555-555555555555';
  v_grant record;
  v_replay record;
  v_job uuid;
  v_other_job uuid;
  v_hold uuid;
  v_second_job uuid;
  v_second_hold uuid;
  v_expiring_job uuid;
  v_expiring_hold uuid;
  v_completed record;
  v_release record;
  v_available bigint;
  v_reserved bigint;
  v_expired bigint;
  v_rejected boolean;
  v_lot_id uuid;
  v_expiry timestamptz;
begin
  insert into auth.users(id) values (v_user), (v_other)
  on conflict (id) do nothing;

  select * into v_grant from public.grant_user_credit_lot(
    v_user, 10, 'free', 'monthly-free-cycle', 'grant-free-lot-001',
    now() + interval '2 days', '{"campaign":"free-cycle-test"}'::jsonb
  );
  if v_grant.available_credits <> 10 or v_grant.reserved_credits <> 0
     or v_grant.replayed then
    raise exception 'Free lot grant returned unexpected wallet state';
  end if;

  select * into v_grant from public.grant_user_credit_lot(
    v_user, 20, 'purchased', 'payment-reference-001', 'grant-purchased-001',
    null, '{"payment_state":"test-only"}'::jsonb
  );
  if v_grant.available_credits <> 30 or v_grant.replayed then
    raise exception 'Purchased lot grant returned unexpected wallet state';
  end if;

  select * into v_replay from public.grant_user_credit_lot(
    v_user, 10, 'free', 'monthly-free-cycle', 'grant-free-lot-001',
    (select expires_at from public.credit_lots
      where user_id = v_user and idempotency_key = 'grant-free-lot-001'),
    '{"campaign":"free-cycle-test"}'::jsonb
  );
  if not v_replay.replayed or v_replay.available_credits <> 30 then
    raise exception 'Repeated lot grant created credits more than once';
  end if;

  v_rejected := false;
  begin
    perform public.grant_user_credit_lot(
      v_user, 11, 'free', 'monthly-free-cycle', 'grant-free-lot-001',
      now() + interval '2 days', '{"campaign":"free-cycle-test"}'::jsonb
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Lot grant idempotency key accepted a changed amount';
  end if;

  v_rejected := false;
  begin
    perform public.grant_user_credit_lot(
      v_user, 4, 'subscription', 'subscription-cycle', 'subscription-no-expiry',
      null, '{}'::jsonb
    );
  exception when sqlstate '22023' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Free/subscription credits were accepted without an expiry date';
  end if;

  select job_id into v_job from public.create_generation_job_with_outbox(
    v_user, null, 'image_generation', 'lot-test-provider', 'lot-test-model',
    'credit-lot-fifo-job-001', repeat('a', 64),
    '{"prompt":"lot FIFO test"}'::jsonb, '{}'::jsonb
  );
  select hold_id into v_hold from public.reserve_job_credits(
    v_user, v_job, 15, 'credit-lot-fifo-hold-001',
    '{"price_version":"lot-test-v1","approved_maximum":15}'::jsonb
  );
  select * into v_replay from public.reserve_job_credits(
    v_user, v_job, 15, 'credit-lot-fifo-hold-001',
    '{"price_version":"lot-test-v1","approved_maximum":15}'::jsonb
  );
  if v_replay.hold_id <> v_hold or not v_replay.replayed
     or v_replay.available_credits <> 15 or v_replay.reserved_credits <> 15 then
    raise exception 'Lot reservation replay changed the reservation or wallet';
  end if;

  if (select sum(a.amount) from public.credit_hold_allocations a
       join public.credit_lots l on l.id = a.lot_id
      where a.hold_id = v_hold and a.status = 'held' and l.lot_type = 'free') <> 10
     or (select sum(a.amount) from public.credit_hold_allocations a
          join public.credit_lots l on l.id = a.lot_id
         where a.hold_id = v_hold and a.status = 'held' and l.lot_type = 'purchased') <> 5 then
    raise exception 'Reservation did not consume earliest-expiring free credits before purchased credits';
  end if;

  select job_id into v_second_job
    from public.create_credited_generation_job_with_outbox(
      v_user, null, null, 'image_generation', 'lot-test-provider', 'lot-test-model',
      'credit-lot-capture-job-001', repeat('b', 64),
      '{"prompt":"lot capture test"}'::jsonb,
      '{"price_version":"lot-test-v1","approved_maximum":5}'::jsonb,
      5
    );
  update public.generation_jobs
     set status = 'running', lease_owner = 'lot-capture-worker',
         lease_expires_at = now() + interval '120 seconds',
         heartbeat_at = now(), updated_at = now()
   where id = v_second_job;
  select * into v_completed from public.complete_credited_generation_job(
    v_second_job, 'lot-capture-worker',
    v_user::text || '/generated/lot-capture.png', repeat('c', 64)
  );
  if not v_completed.completed or v_completed.replayed
     or v_completed.available_credits <> 10 or v_completed.reserved_credits <> 15 then
    raise exception 'Successful generation did not capture exactly its allocated lot credits';
  end if;
  if not exists (
    select 1 from public.credit_hold_allocations
     where hold_id = (select id from public.credit_holds where job_id = v_second_job)
       and status = 'captured'
  ) then
    raise exception 'Captured generation did not terminalize its lot allocations';
  end if;

  if not exists (
    select 1 from public.credit_ledger
     where hold_id = (select id from public.credit_holds where job_id = v_second_job)
       and operation_type = 'capture'
       and metadata->>'result_storage_path' = v_user::text || '/generated/lot-capture.png'
       and metadata->>'result_sha256' = repeat('c', 64)
  ) then
    raise exception 'Capture ledger did not preserve verified result path and SHA-256';
  end if;

  update public.generation_jobs
     set status = 'failed', last_error_code = 'lot_release_test',
         completed_at = now(), updated_at = now()
   where id = v_job;
  select * into v_release from public.release_job_credit_hold(
    v_user, v_hold, 'lot_release_test'
  );
  if v_release.available_credits <> 25 or v_release.reserved_credits <> 0
     or v_release.replayed then
    raise exception 'Release did not restore unexpired allocated lot balances';
  end if;

  -- Replaying the original reservation after the job became terminal is a
  -- read-only idempotent response, never a second hold or balance mutation.
  select * into v_replay from public.reserve_job_credits(
    v_user, v_job, 15, 'credit-lot-fifo-hold-001',
    '{"price_version":"lot-test-v1","approved_maximum":15}'::jsonb
  );
  if v_replay.hold_id <> v_hold or not v_replay.replayed
     or v_replay.available_credits <> 25 or v_replay.reserved_credits <> 0
     or (select count(*) from public.credit_holds
          where user_id = v_user and operation_key = 'credit-lot-fifo-hold-001') <> 1 then
    raise exception 'Terminal reservation replay changed the original hold or wallet';
  end if;

  if exists (
    select 1 from public.credit_hold_allocations
     where hold_id = v_hold and status <> 'released'
  ) then
    raise exception 'Released hold retained an active lot allocation';
  end if;

  select * into v_grant from public.grant_user_credit_lot(
    v_user, 5, 'bonus', 'short-lived-bonus', 'grant-expiring-reserved-001',
    now() + interval '1 second', '{"test_case":"expiry-while-held"}'::jsonb
  );
  select job_id into v_expiring_job from public.create_generation_job_with_outbox(
    v_user, null, 'image_generation', 'lot-test-provider', 'lot-test-model',
    'credit-lot-expiring-job-001', repeat('d', 64),
    '{"prompt":"expiry while held"}'::jsonb, '{}'::jsonb
  );
  select hold_id into v_expiring_hold from public.reserve_job_credits(
    v_user, v_expiring_job, 5, 'credit-lot-expiring-hold-001',
    '{"price_version":"lot-test-v1","approved_maximum":5}'::jsonb
  );
  select id into v_lot_id from public.credit_lots
   where user_id = v_user and idempotency_key = 'grant-expiring-reserved-001';
  if not exists (
    select 1 from public.credit_hold_allocations
     where hold_id = v_expiring_hold and lot_id = v_lot_id and amount = 5
  ) then
    raise exception 'The soonest-expiring bonus lot was not selected first';
  end if;

  update public.credit_lots
     set created_at = now() - interval '10 seconds',
         expires_at = now() - interval '1 second'
   where id = v_lot_id;
  update public.generation_jobs
     set status = 'failed', last_error_code = 'expired_lot_release_test',
         completed_at = now(), updated_at = now()
   where id = v_expiring_job;
  select * into v_release from public.release_job_credit_hold(
    v_user, v_expiring_hold, 'expired_lot_release_test'
  );
  if v_release.available_credits <> 25 or v_release.reserved_credits <> 0 then
    raise exception 'Expired reserved credits were incorrectly restored on release';
  end if;
  if not exists (
    select 1 from public.credit_ledger
     where hold_id = v_expiring_hold and operation_type = 'release'
       and (metadata->>'expired_credits_forfeited')::bigint = 5
  ) then
    raise exception 'Expired reserved credits were not recorded as forfeited';
  end if;

  v_expiry := now() + interval '1 second';
  select * into v_grant from public.grant_user_credit_lot(
    v_user, 7, 'free', 'expired-free-cycle', 'grant-expired-free-001',
    v_expiry, '{"test_case":"available-expiry"}'::jsonb
  );
  -- Move the test lot past its deadline explicitly. The expiry RPC uses
  -- transaction-stable now(), and this entire DO block is one transaction.
  update public.credit_lots
     set created_at = now() - interval '10 seconds',
         expires_at = now() - interval '1 second'
   where user_id = v_user and idempotency_key = 'grant-expired-free-001';
  v_expired := public.expire_credit_lots_for_user(v_user);
  if v_expired <> 7 then
    raise exception 'Expiry sweep did not expire the exact available lot amount';
  end if;

  select available_credits, reserved_credits into v_available, v_reserved
    from public.credit_wallets where user_id = v_user;
  if v_available <> 25 or v_reserved <> 0 then
    raise exception 'Expiry sweep did not reconcile wallet and lot balances';
  end if;
  if not exists (
    select 1 from public.credit_ledger
     where user_id = v_user and operation_key like 'expire:%'
       and operation_type = 'adjustment' and delta_available = -7
  ) then
    raise exception 'Expired available credits are missing their compensating ledger entry';
  end if;

  select job_id into v_other_job from public.create_generation_job_with_outbox(
    v_other, null, 'image_generation', 'lot-test-provider', 'lot-test-model',
    'credit-lot-other-user-job', repeat('e', 64),
    '{"prompt":"owner isolation"}'::jsonb, '{}'::jsonb
  );
  v_rejected := false;
  begin
    perform public.reserve_job_credits(
      v_user, v_other_job, 1, 'credit-lot-cross-user-001',
      '{"price_version":"lot-test-v1","approved_maximum":1}'::jsonb
    );
  exception when sqlstate 'P0002' then v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'A user was able to reserve credits against another owner''s job';
  end if;

  select coalesce(sum(available_credits), 0),
         coalesce(sum(reserved_credits), 0)
    into v_expired, v_reserved
    from public.credit_lots where user_id = v_user;
  if v_expired <> v_available or v_reserved <> 0 then
    raise exception 'Final lot totals do not reconcile with the wallet';
  end if;
end;
$credit_lot_lifecycle_test$;

-- Exercise a genuine delayed retry across committed transactions. The lot's
-- immutable original expiry timestamp is never edited: time advances between
-- the grant and replay, so the replay validates the real post-expiry contract.
do $expired_grant_replay_setup$
declare
  v_user uuid := '66666666-6666-4666-8666-666666666666';
begin
  insert into auth.users(id) values (v_user) on conflict (id) do nothing;
  perform * from public.grant_user_credit_lot(
    v_user, 7, 'free', 'delayed-retry-cycle', 'grant-delayed-expiry-001',
    now() + interval '1 second', '{"test_case":"real-delayed-expiry-replay"}'::jsonb
  );
end;
$expired_grant_replay_setup$;

select pg_sleep(2);

do $expired_grant_replay_assert$
declare
  v_user uuid := '66666666-6666-4666-8666-666666666666';
  v_expiry timestamptz;
  v_replay record;
  v_lot_count integer;
  v_expired_ledger_count integer;
begin
  select expires_at into strict v_expiry
    from public.credit_lots
   where user_id = v_user and idempotency_key = 'grant-delayed-expiry-001';

  select * into v_replay from public.grant_user_credit_lot(
    v_user, 7, 'free', 'delayed-retry-cycle', 'grant-delayed-expiry-001',
    v_expiry, '{"test_case":"real-delayed-expiry-replay"}'::jsonb
  );

  select count(*) into v_lot_count
    from public.credit_lots
   where user_id = v_user and idempotency_key = 'grant-delayed-expiry-001';
  select count(*) into v_expired_ledger_count
    from public.credit_ledger
   where user_id = v_user and operation_key like 'expire:%'
     and operation_type = 'adjustment' and delta_available = -7;

  if not v_replay.replayed
     or v_replay.available_credits <> 0
     or v_replay.reserved_credits <> 0
     or v_lot_count <> 1
     or v_expired_ledger_count <> 1 then
    raise exception 'Delayed grant replay after real expiry restored or duplicated credits';
  end if;
end;
$expired_grant_replay_assert$;

select 'source-separated credit lot lifecycle checks passed' as result;

select 'credit wallet snapshot checks passed' as result;


-- Verify read-only wallet reconciliation keyset pagination and legacy fail-closed behavior.
do $wallet_reconciliation_pagination_test$
declare
  v_user_one uuid := 'ffffffff-ffff-4fff-8fff-000000000001';
  v_user_two uuid := 'ffffffff-ffff-4fff-8fff-000000000002';
  v_user_three uuid := 'ffffffff-ffff-4fff-8fff-000000000003';
  v_cursor uuid;
  v_page_count integer;
  v_has_more boolean;
  v_rejected boolean := false;
begin
  insert into auth.users(id) values
    (v_user_one), (v_user_two), (v_user_three)
  on conflict (id) do nothing;

  insert into public.credit_ledger(
    user_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values
    (v_user_one, 'grant', 'grant:reconcile-page-one', 1, 0, 1, 0, '{"test_case":"reconciliation-pagination"}'::jsonb),
    (v_user_two, 'grant', 'grant:reconcile-page-two', 1, 0, 1, 0, '{"test_case":"reconciliation-pagination"}'::jsonb),
    (v_user_three, 'grant', 'grant:reconcile-page-three', 1, 0, 1, 0, '{"test_case":"reconciliation-pagination"}'::jsonb)
  on conflict do nothing;

  select count(*)::integer, coalesce(bool_and(page.has_more), false)
    into v_page_count, v_has_more
    from public.audit_credit_wallet_reconciliation_page(
      null, 'ffffffff-ffff-4fff-8fff-000000000000', 2
    ) page;

  select page.user_id into v_cursor
    from public.audit_credit_wallet_reconciliation_page(
      null, 'ffffffff-ffff-4fff-8fff-000000000000', 2
    ) page
   order by page.user_id desc
   limit 1;

  if v_page_count <> 2 or not v_has_more
     or v_cursor <> v_user_two then
    raise exception 'First reconciliation page did not return two ordered rows with has_more=true';
  end if;

  select count(*)::integer, coalesce(bool_and(page.has_more), true)
    into v_page_count, v_has_more
    from public.audit_credit_wallet_reconciliation_page(null, v_cursor, 2) page;

  if v_page_count <> 1 or v_has_more then
    raise exception 'Second reconciliation page did not return the final row with has_more=false';
  end if;

  begin
    perform *
      from public.audit_credit_wallet_reconciliation(null, 2);
  exception when sqlstate '22023' then
    v_rejected := true;
  end;

  if not v_rejected then
    raise exception 'Legacy reconciliation RPC silently returned a partial result instead of rejecting';
  end if;

  if has_function_privilege('authenticated',
       'public.audit_credit_wallet_reconciliation_page(uuid,uuid,integer)', 'EXECUTE') then
    raise exception 'Authenticated role can invoke privileged paginated reconciliation';
  end if;
end;
$wallet_reconciliation_pagination_test$;

select 'wallet reconciliation pagination checks passed' as result;


-- Administrative audit journal: only service_role can call bounded RPCs;
-- table access is denied and existing rows cannot be updated or deleted.
do $$
declare
  v_actor uuid := '11111111-1111-4111-8111-111111111111';
  v_event uuid;
  v_event_second uuid;
  v_cursor record;
  v_count integer;
  v_mutation_blocked boolean := false;
begin
  v_event := public.record_admin_audit_event(
    v_actor, 'admin.access', 'allowed', 'platform', null, gen_random_uuid(),
    'Read-only integration fixture'
  );
  if v_event is null then
    raise exception 'audit insert did not return an event id';
  end if;
  v_event_second := public.record_admin_audit_event(
    v_actor, 'admin.access', 'allowed', 'platform', null, gen_random_uuid(),
    'Second pagination fixture with same transaction timestamp'
  );

  select count(*) into v_count
    from public.read_admin_audit_events(null, null, 10)
   where id = v_event and actor_user_id = v_actor
     and action = 'admin.access' and outcome = 'allowed';
  if v_count <> 1 then
    raise exception 'audit event could not be read through the bounded RPC';
  end if;

  select occurred_at, id into v_cursor
    from public.admin_audit_events
   where id in (v_event, v_event_second)
   order by occurred_at desc, id desc
   limit 1;
  select count(*) into v_count
    from public.read_admin_audit_events(v_cursor.occurred_at, v_cursor.id, 10)
   where id in (v_event, v_event_second);
  if v_count <> 1 then
    raise exception 'composite audit cursor skipped or duplicated same-timestamp events';
  end if;

  begin
    update public.admin_audit_events set reason = 'tampered' where id = v_event;
  exception when sqlstate '55000' then
    v_mutation_blocked := true;
  end;
  if not v_mutation_blocked then
    raise exception 'audit update was not blocked';
  end if;

  begin
    delete from public.admin_audit_events where id = v_event;
    raise exception 'audit delete was not blocked';
  exception when sqlstate '55000' then
    null;
  end;

  begin
    perform public.record_admin_audit_event(
      v_actor, 'unknown.action', 'allowed', 'platform'
    );
    raise exception 'unknown audit action was accepted';
  exception when sqlstate '22023' then
    null;
  end;

  begin
    perform * from public.read_admin_audit_events(null, null, 201);
    raise exception 'unbounded audit page was accepted';
  exception when sqlstate '22023' then
    null;
  end;
end;
$$;


-- Delegated finance assignments are private, immutable records. Until a reviewed
-- server-side assignment RPC exists, even service_role has no direct table access.
do $finance_authorization_registry_test$
declare
  v_assignment uuid;
  v_event uuid;
  v_blocked boolean;
begin
  if not (
    select relrowsecurity from pg_class
     where oid = 'public.finance_role_assignments'::regclass
  ) or not (
    select relrowsecurity from pg_class
     where oid = 'public.finance_role_revocations'::regclass
  ) or not (
    select relrowsecurity from pg_class
     where oid = 'public.finance_authorization_events'::regclass
  ) then
    raise exception 'Finance authorization registry tables must enforce RLS';
  end if;

  if has_table_privilege('anon', 'public.finance_role_assignments', 'SELECT')
     or has_table_privilege('authenticated', 'public.finance_role_assignments', 'SELECT')
     or has_table_privilege('service_role', 'public.finance_role_assignments', 'SELECT')
     or has_table_privilege('service_role', 'public.finance_role_assignments', 'INSERT')
     or has_table_privilege('service_role', 'public.finance_role_revocations', 'INSERT')
     or has_table_privilege('service_role', 'public.finance_authorization_events', 'INSERT') then
    raise exception 'Application roles unexpectedly have direct finance registry table access';
  end if;

  insert into public.finance_role_assignments(
    principal_id, role_code, scope_key, valid_from, valid_until, granted_by, reason
  ) values (
    '22222222-2222-4222-8222-222222222222',
    'finance_operator', 'test-scope',
    now(), now() + interval '1 day',
    '11111111-1111-4111-8111-111111111111',
    'Disposable integration fixture'
  ) returning id into v_assignment;

  v_blocked := false;
  begin
    update public.finance_role_assignments
       set reason = 'tampered fixture'
     where id = v_assignment;
  exception when sqlstate '55000' then
    v_blocked := true;
  end;
  if not v_blocked then
    raise exception 'Finance role grant history was mutable';
  end if;

  insert into public.finance_role_revocations(
    assignment_id, revoked_by, reason
  ) values (
    v_assignment, '11111111-1111-4111-8111-111111111111',
    'Disposable revocation fixture'
  );

  v_blocked := false;
  begin
    update public.finance_role_revocations
       set reason = 'tampered revocation'
     where assignment_id = v_assignment;
  exception when sqlstate '55000' then
    v_blocked := true;
  end;
  if not v_blocked then
    raise exception 'Finance role revocation history was mutable';
  end if;

  insert into public.finance_authorization_events(
    assignment_id, actor_user_id, target_principal_id,
    event_type, role_code, scope_key, reason
  ) values (
    v_assignment,
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    'role.granted', 'finance_operator', 'test-scope',
    'Disposable authorization event fixture'
  ) returning id into v_event;

  v_blocked := false;
  begin
    delete from public.finance_authorization_events where id = v_event;
  exception when sqlstate '55000' then
    v_blocked := true;
  end;
  if not v_blocked then
    raise exception 'Finance authorization event history was deletable';
  end if;
end;
$finance_authorization_registry_test$;

select 'finance authorization registry security checks passed' as result;


-- Server-only registry RPCs atomically write grant/revoke events and expose only
-- currently active assignments. Browser roles cannot invoke these functions.
do $finance_role_registry_rpc_test$
declare
  v_assignment uuid;
  v_revocation uuid;
  v_active_count integer;
  v_event_count integer;
  v_rejected boolean := false;
begin
  if not has_function_privilege('service_role',
       'public.read_active_finance_role_assignments(uuid)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.grant_finance_role(uuid,text,text,timestamp with time zone,uuid,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.revoke_finance_role(uuid,uuid,text)', 'EXECUTE') then
    raise exception 'service_role is missing finance registry RPC access';
  end if;

  if has_function_privilege('authenticated',
       'public.read_active_finance_role_assignments(uuid)', 'EXECUTE')
     or has_function_privilege('anon',
       'public.grant_finance_role(uuid,text,text,timestamp with time zone,uuid,text)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.revoke_finance_role(uuid,uuid,text)', 'EXECUTE') then
    raise exception 'Browser role can invoke privileged finance registry RPC';
  end if;

  v_assignment := public.grant_finance_role(
    '22222222-2222-4222-8222-222222222222',
    'finance_operator', 'test-scope', now() + interval '1 day',
    '11111111-1111-4111-8111-111111111111',
    'Disposable registry RPC grant fixture'
  );

  select count(*) into v_active_count
    from public.read_active_finance_role_assignments(
      '22222222-2222-4222-8222-222222222222'
    )
   where assignment_id = v_assignment
     and role_code = 'finance_operator'
     and scope_key = 'test-scope';
  if v_active_count <> 1 then
    raise exception 'New finance assignment was not returned as active';
  end if;

  select count(*) into v_event_count
    from public.finance_authorization_events
   where assignment_id = v_assignment and event_type = 'role.granted';
  if v_event_count <> 1 then
    raise exception 'Finance role grant did not atomically create its audit event';
  end if;

  v_rejected := false;
  begin
    perform public.grant_finance_role(
      '22222222-2222-4222-8222-222222222222',
      'finance_operator', 'test-scope', now() + interval '1 day',
      '11111111-1111-4111-8111-111111111111',
      'Duplicate active assignment fixture'
    );
  exception when sqlstate '23505' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Duplicate active finance role assignment was accepted';
  end if;

  v_revocation := public.revoke_finance_role(
    v_assignment,
    '11111111-1111-4111-8111-111111111111',
    'Disposable registry RPC revoke fixture'
  );
  if v_revocation is null then
    raise exception 'Finance role revocation did not return an id';
  end if;

  select count(*) into v_active_count
    from public.read_active_finance_role_assignments(
      '22222222-2222-4222-8222-222222222222'
    )
   where assignment_id = v_assignment;
  if v_active_count <> 0 then
    raise exception 'Revoked finance assignment remained active';
  end if;

  select count(*) into v_event_count
    from public.finance_authorization_events
   where assignment_id = v_assignment
     and event_type in ('role.granted', 'role.revoked');
  if v_event_count <> 2 then
    raise exception 'Grant and revoke lifecycle is missing an audit event';
  end if;

  v_rejected := false;
  begin
    perform public.grant_finance_role(
      '22222222-2222-4222-8222-222222222222',
      'unknown_role', null, null,
      '11111111-1111-4111-8111-111111111111', 'invalid role fixture'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Unknown finance role was accepted';
  end if;
  v_rejected := false;
  begin
    perform public.grant_finance_role(
      '11111111-1111-4111-8111-111111111111',
      'finance_operator', null, null,
      '11111111-1111-4111-8111-111111111111', 'self grant must fail'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Self-assignment of finance role was accepted';
  end if;

  v_rejected := false;
  begin
    perform public.grant_finance_role(
      '22222222-2222-4222-8222-222222222222',
      'finance_operator', null, now() + interval '1 day',
      '11111111-1111-4111-8111-111111111111', 'missing scope fixture'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Unscoped finance role assignment was accepted';
  end if;

  v_rejected := false;
  begin
    perform public.grant_finance_role(
      '22222222-2222-4222-8222-222222222222',
      'finance_operator', 'test-scope', null,
      '11111111-1111-4111-8111-111111111111', 'missing expiry fixture'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Non-expiring finance role assignment was accepted';
  end if;
end;
$finance_role_registry_rpc_test$;

select 'finance role registry RPC checks passed' as result;

-- Finance request state transitions are transactional, idempotent, and non-executable.
do $finance_operation_request_test$
declare
  v_request uuid;
  v_replay uuid;
  v_cancel_request uuid;
  v_queue_request uuid;
  v_queue_count integer;
  v_event_count integer;
  v_status text;
  v_rejected boolean := false;
begin
  if has_table_privilege('anon', 'public.finance_operation_requests', 'SELECT')
     or has_table_privilege('authenticated', 'public.finance_operation_requests', 'SELECT')
     or has_table_privilege('service_role', 'public.finance_operation_requests', 'SELECT')
     or has_table_privilege('authenticated', 'public.finance_operation_request_events', 'INSERT')
     or has_function_privilege('authenticated',
       'public.create_finance_operation_request(uuid,text,uuid,numeric,text,text,text,uuid)', 'EXECUTE')
     or has_function_privilege('anon',
       'public.decide_finance_operation_request(uuid,uuid,text,text)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.read_finance_operation_request(uuid)', 'EXECUTE')
     or has_function_privilege('authenticated',
       'public.read_finance_operation_request(uuid)', 'EXECUTE') then
    raise exception 'Finance request storage or RPCs expose excessive privileges';
  end if;

  v_request := public.create_finance_operation_request(
    '11111111-1111-4111-8111-111111111111',
    'credit_compensation',
    '22222222-2222-4222-8222-222222222222',
    12, 'CRD', 'user:22222222-2222-4222-8222-222222222222', 'Compensation review fixture',
    'aaaaaaaa-1111-4111-8111-111111111111'
  );
  v_replay := public.create_finance_operation_request(
    '11111111-1111-4111-8111-111111111111',
    'credit_compensation',
    '22222222-2222-4222-8222-222222222222',
    12, 'CRD', 'user:22222222-2222-4222-8222-222222222222', 'Compensation review fixture',
    'aaaaaaaa-1111-4111-8111-111111111111'
  );
  if v_request <> v_replay then
    raise exception 'Idempotent request replay returned a different request id';
  end if;

  select count(*) into v_event_count
    from public.read_finance_operation_request(v_request)
   where request_id = v_request
     and requester_id = '11111111-1111-4111-8111-111111111111'
     and target_user_id = '22222222-2222-4222-8222-222222222222'
     and scope_key = 'user:22222222-2222-4222-8222-222222222222'
     and status = 'pending';
  if v_event_count <> 1 then
    raise exception 'Server-only finance request lookup returned incorrect data';
  end if;

  v_queue_request := public.create_finance_operation_request(
    '11111111-1111-4111-8111-111111111111',
    'credit_compensation',
    '22222222-2222-4222-8222-222222222222',
    5, 'CRD', 'user:22222222-2222-4222-8222-222222222222',
    'Queue scope fixture',
    '99999999-9999-4999-8999-999999999999'
  );
  select count(*) into v_queue_count
    from public.list_finance_operation_requests(
      array['user:22222222-2222-4222-8222-222222222222']::text[],
      array[]::text[], 'pending', null, null, 10
    )
   where request_id = v_queue_request;
  if v_queue_count <> 1 then
    raise exception 'Finance queue did not return the explicitly allowed scope';
  end if;
  select count(*) into v_queue_count
    from public.list_finance_operation_requests(
      array['user:33333333-3333-4333-8333-333333333333']::text[],
      array[]::text[], null, null, null, 10
    );
  if v_queue_count <> 0 then
    raise exception 'Finance queue leaked a request outside the requested scope';
  end if;
  if has_function_privilege('authenticated',
       'public.list_finance_operation_requests(text[],text[],text,timestamptz,uuid,integer)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.list_finance_operation_requests(text[],text[],text,timestamptz,uuid,integer)', 'EXECUTE') then
    raise exception 'Finance queue RPC has excessive privileges';
  end if;

  v_rejected := false;
  begin
    perform public.create_finance_operation_request(
      '11111111-1111-4111-8111-111111111111',
      'credit_compensation',
      '22222222-2222-4222-8222-222222222222',
      99, 'CRD', 'user:22222222-2222-4222-8222-222222222222', 'Changed payload',
      'aaaaaaaa-1111-4111-8111-111111111111'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Changed request payload reused an idempotency key';
  end if;

  v_rejected := false;
  begin
    perform public.create_finance_operation_request(
      '11111111-1111-4111-8111-111111111111',
      'credit_compensation',
      '22222222-2222-4222-8222-222222222222',
      'NaN'::numeric, 'CRD', 'user:22222222-2222-4222-8222-222222222222', 'Non-finite amount',
      'cccccccc-3333-4333-8333-333333333333'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Non-finite finance amount was accepted';
  end if;

  v_rejected := false;
  begin
    perform public.create_finance_operation_request(
      '11111111-1111-4111-8111-111111111111',
      'billing_refund',
      '22222222-2222-4222-8222-222222222222',
      0.00001, 'USD', 'user:22222222-2222-4222-8222-222222222222', 'Excess scale amount',
      'dddddddd-4444-4444-8444-444444444444'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Finance amount with excessive scale was accepted';
  end if;

  v_rejected := false;
  begin
    perform public.create_finance_operation_request(
      '11111111-1111-4111-8111-111111111111',
      'credit_compensation',
      '22222222-2222-4222-8222-222222222222',
      1.5, 'CRD', 'user:22222222-2222-4222-8222-222222222222', 'Fractional credits',
      'eeeeeeee-5555-4555-8555-555555555555'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Fractional credit compensation was accepted';
  end if;

  v_rejected := false;
  begin
    perform public.create_finance_operation_request(
      '11111111-1111-4111-8111-111111111111',
      'credit_compensation',
      '22222222-2222-4222-8222-222222222222',
      1, 'CRD', 'user:11111111-1111-4111-8111-111111111111',
      'Mismatched target scope',
      '88888888-8888-4888-8888-888888888888'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Finance request accepted a scope for a different target';
  end if;

  v_rejected := false;
  begin
    perform public.decide_finance_operation_request(
      v_request, '11111111-1111-4111-8111-111111111111',
      'approve', 'Self approval fixture'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Requester approved their own finance request';
  end if;

  perform public.decide_finance_operation_request(
    v_request, '22222222-2222-4222-8222-222222222222',
    'approve', 'Independent approval fixture'
  );
  select status into v_status from public.finance_operation_requests where id = v_request;
  if v_status <> 'approved' then
    raise exception 'Finance request was not approved';
  end if;

  v_rejected := false;
  begin
    perform public.decide_finance_operation_request(
      v_request, '22222222-2222-4222-8222-222222222222',
      'approve', 'Repeated approval fixture'
    );
  exception when sqlstate '55000' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'A finance request was decided more than once';
  end if;

  v_cancel_request := public.create_finance_operation_request(
    '22222222-2222-4222-8222-222222222222',
    'billing_refund',
    '11111111-1111-4111-8111-111111111111',
    4.0000, 'USD', 'user:11111111-1111-4111-8111-111111111111', 'Cancellation review fixture',
    'bbbbbbbb-2222-4222-8222-222222222222'
  );
  v_rejected := false;
  begin
    perform public.cancel_finance_operation_request(
      v_cancel_request, '11111111-1111-4111-8111-111111111111',
      'Wrong actor cancellation'
    );
  exception when sqlstate '22023' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Non-requester cancelled a finance request';
  end if;

  perform public.cancel_finance_operation_request(
    v_cancel_request, '22222222-2222-4222-8222-222222222222',
    'Requester cancellation fixture'
  );
  select status into v_status from public.finance_operation_requests where id = v_cancel_request;
  if v_status <> 'cancelled' then
    raise exception 'Pending finance request was not cancelled';
  end if;

  select count(*) into v_event_count
    from public.finance_operation_request_events
   where request_id = v_request;
  if v_event_count <> 2 then
    raise exception 'Finance request audit stream has unexpected event count';
  end if;
  select count(*) into v_event_count
    from public.read_finance_operation_request_events(v_request)
   where (event_type = 'request.created' and previous_status is null and new_status = 'pending')
      or (event_type = 'request.approved' and previous_status = 'pending' and new_status = 'approved');
  if v_event_count <> 2 then
    raise exception 'Server-only finance event timeline returned an incorrect history';
  end if;
  if has_function_privilege('authenticated',
       'public.read_finance_operation_request_events(uuid)', 'EXECUTE')
     or not has_function_privilege('service_role',
       'public.read_finance_operation_request_events(uuid)', 'EXECUTE') then
    raise exception 'Finance event timeline RPC has excessive privileges';
  end if;

  v_rejected := false;
  begin
    delete from public.finance_operation_request_events
     where request_id = v_request;
  exception when sqlstate '55000' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Finance operation request event history was mutable';
  end if;
end;
$finance_operation_request_test$;

select 'finance operation request lifecycle checks passed' as result;



-- Customer-plan quota admission migrations and transactional job integration.
\ir ../migrations/0056_pricing_catalog_drafts.sql
\ir ../migrations/0057_plan_catalog_drafts.sql
\ir ../migrations/0058_seed_inactive_free_entitlement.sql
\ir ../migrations/0059_ai_monthly_admission_limits.sql
\ir ../migrations/0060_plan_approval_and_assignment_foundation.sql
\ir ../migrations/0061_plan_approval_assignment_rpcs.sql
\ir ../migrations/0062_plan_approval_audit_atomicity.sql
\ir ../migrations/0063_pending_assignment_audit_and_idempotency.sql
\ir ../migrations/0064_atomic_plan_quota_reservations.sql
\ir ../migrations/0065_plan_quota_window_semantics.sql
\ir ../migrations/0066_plan_quota_rpc_only_privileges.sql
\ir ../migrations/0067_atomic_plan_credited_generation.sql
\ir ../migrations/0068_resolve_plan_quotas_with_job_lifecycle.sql
\ir ../migrations/0069_enforce_generation_job_and_video_plan_limits.sql
\ir ../migrations/0070_private_character_reference_storage.sql
\ir ../migrations/0071_character_visual_asset_metadata.sql

-- Verify private bucket settings, metadata RLS, and account isolation.
do $visual_asset_migration_test$
declare
  v_policy_count integer;
begin
  if not exists (
    select 1 from storage.buckets
    where id = 'character-references'
      and public = false
      and file_size_limit = 8388608
      and allowed_mime_types = array['image/png','image/jpeg','image/webp']::text[]
  ) then
    raise exception 'Character reference bucket privacy or upload constraints are incorrect';
  end if;
  if not (select relrowsecurity from pg_class where oid = 'public.character_visual_assets'::regclass) then
    raise exception 'Character visual asset metadata table must enforce RLS';
  end if;
  select count(*) into v_policy_count
    from pg_policies
   where schemaname = 'public'
     and tablename = 'character_visual_assets'
     and roles @> array['authenticated']::name[];
  if v_policy_count <> 4 then
    raise exception 'Expected four authenticated owner-scoped metadata policies';
  end if;
  if has_table_privilege('anon','public.character_visual_assets','select') then
    raise exception 'Anonymous users must not receive visual asset metadata access';
  end if;
end;
$visual_asset_migration_test$;

insert into auth.users(id) values
  ('abababab-abab-4bab-8bab-abababababab'),
  ('cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd')
on conflict (id) do nothing;
grant select, insert, update, delete on storage.objects to authenticated;
set role authenticated;
select set_config('request.jwt.claim.sub','abababab-abab-4bab-8bab-abababababab',false);
insert into public.character_visual_assets(user_id,asset_id,asset)
values ('abababab-abab-4bab-8bab-abababababab','visual-owner-test',
        '{"id":"visual-owner-test","name":"Private test"}'::jsonb);
do $visual_asset_rls_test$
begin
  if (select count(*) from public.character_visual_assets) <> 1 then
    raise exception 'Authenticated owner cannot read their own visual asset';
  end if;
  begin
    insert into public.character_visual_assets(user_id,asset_id,asset)
    values ('cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd','visual-cross-user-test',
            '{"id":"visual-cross-user-test"}'::jsonb);
    raise exception 'Cross-user visual asset insert unexpectedly succeeded';
  exception when insufficient_privilege then
    null;
  end;
end;
$visual_asset_rls_test$;
reset role;
delete from public.character_visual_assets
where asset_id = 'visual-owner-test';


insert into public.plan_catalog_drafts(
  id, plan_code, plan_version, display_name, billing_period, period_days,
  credits_per_period, limits_json, features_json, created_by
) values (
  '12121212-1212-4121-8121-121212121212',
  'test_creator', 1, 'Test Creator', 'month', 30, 1000,
  '{
    "daily_ai_requests": 20,
    "monthly_ai_requests": 200,
    "max_concurrent_ai_requests": 1,
    "daily_image_generations": 10,
    "monthly_image_generations": 100,
    "daily_video_generations": 5,
    "monthly_video_generations": 40,
    "daily_audio_generations": 10,
    "monthly_audio_generations": 100,
    "daily_generation_jobs": 20,
    "monthly_generation_jobs": 100,
    "max_parallel_jobs": 2,
    "max_video_seconds": 60,
    "max_resolution": "1080p"
  }'::jsonb,
  '["image","video","audio","ai"]'::jsonb,
  '11111111-1111-4111-8111-111111111111'
);

insert into public.approved_plan_versions(
  id, source_draft_id, plan_code, plan_version, display_name,
  billing_period, period_days, credits_per_period, limits_json,
  features_json, approved_by, approval_reason
) values (
  '13131313-1313-4131-8131-131313131313',
  '12121212-1212-4121-8121-121212121212',
  'test_creator', 1, 'Test Creator', 'month', 30, 1000,
  (select limits_json from public.plan_catalog_drafts
    where id = '12121212-1212-4121-8121-121212121212'),
  '["image","video","audio","ai"]'::jsonb,
  '11111111-1111-4111-8111-111111111111',
  'Approved fixture plan for integration testing'
);

insert into public.user_plan_assignments(
  id, user_id, approved_plan_version_id, assignment_source,
  source_reference, idempotency_key, status, starts_at, ends_at, created_by
) values (
  '14141414-1414-4141-8141-141414141414',
  '22222222-2222-4222-8222-222222222222',
  '13131313-1313-4131-8131-131313131313',
  'operator_grant', 'test-fixture-plan', 'test-fixture-plan-001',
  'pending', now() - interval '1 minute', now() + interval '30 days',
  '11111111-1111-4111-8111-111111111111'
);

insert into public.user_plan_assignment_events(
  assignment_id, user_id, event_type, actor_user_id, event_key, reason
) values (
  '14141414-1414-4141-8141-141414141414',
  '22222222-2222-4222-8222-222222222222',
  'activated',
  '11111111-1111-4111-8111-111111111111',
  'activated:fixture-plan-001',
  'Test-only activation event for quota integration'
);

select public.grant_user_credit_lot(
  '22222222-2222-4222-8222-222222222222',
  1000, 'bonus', 'plan-quota-test-credit',
  'plan-quota-fixture-grant-001',
  now() + interval '30 days',
  '{"test_fixture":true}'::jsonb
);

do $plan_quota_atomic_admission_test$
declare
  v_created record;
  v_job_id uuid;
  v_before_available bigint;
  v_after_available bigint;
  v_before_jobs integer;
  v_after_jobs integer;
  v_before_holds integer;
  v_after_holds integer;
  v_reservations integer;
  v_completed integer;
begin
  select available_credits into v_before_available
    from public.credit_wallets
   where user_id = '22222222-2222-4222-8222-222222222222';
  select count(*) into v_before_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';
  select count(*) into v_before_holds from public.credit_holds
   where user_id = '22222222-2222-4222-8222-222222222222';

  select * into v_created
    from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      null,
      'abababab-abab-4bab-8bab-abababababab',
      'image_generation',
      'quota-test-provider',
      'quota-test-model',
      'plan-quota-image-job-001',
      repeat('a', 64),
      '{"prompt":"atomic quota integration test","quantity":2}'::jsonb,
      '{"amount":20,"quantity":2,"price_version":"test-v1"}'::jsonb,
      20
    );

  v_job_id := v_created.job_id;
  if not v_created.created or v_created.replayed then
    raise exception 'First plan-based generation admission was not a new job';
  end if;
  if jsonb_array_length(v_created.quota_reservations) <> 5 then
    raise exception 'Image job must reserve image, general-job, and parallel quota dimensions';
  end if;
  if (select count(*) from public.plan_quota_reservations
       where user_id = '22222222-2222-4222-8222-222222222222'
         and request_id = v_job_id and status = 'reserved') <> 5 then
    raise exception 'Plan quota reservations were not persisted with the job';
  end if;
  if (select count(*) from public.outbox_events
       where aggregate_id = v_job_id and event_type = 'generation_job.created') <> 1 then
    raise exception 'Atomic plan-based admission must create exactly one outbox event';
  end if;

  -- The daily image quota is 10; 2 units are already reserved.
  -- A second 9-unit request must roll back its job, outbox and credit hold.
  select count(*) into v_before_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';
  select count(*) into v_before_holds from public.credit_holds
   where user_id = '22222222-2222-4222-8222-222222222222';
  select available_credits into v_before_available
    from public.credit_wallets
   where user_id = '22222222-2222-4222-8222-222222222222';

  begin
    perform * from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      null,
      'abababab-abab-4bab-8bab-abababababab',
      'image_generation',
      'quota-test-provider',
      'quota-test-model',
      'plan-quota-image-job-overflow',
      repeat('b', 64),
      '{"prompt":"must roll back","quantity":9}'::jsonb,
      '{"amount":90,"quantity":9,"price_version":"test-v1"}'::jsonb,
      90
    );
    raise exception 'Over-quota image job was unexpectedly admitted';
  exception when sqlstate '54000' then
    null;
  end;

  select count(*) into v_after_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';
  select count(*) into v_after_holds from public.credit_holds
   where user_id = '22222222-2222-4222-8222-222222222222';
  select available_credits into v_after_available
    from public.credit_wallets
   where user_id = '22222222-2222-4222-8222-222222222222';
  if v_after_jobs <> v_before_jobs or v_after_holds <> v_before_holds
     or v_after_available <> v_before_available then
    raise exception 'Quota denial did not roll back job, hold and wallet atomically';
  end if;

  update public.generation_jobs
     set status = 'succeeded', completed_at = now(), updated_at = now()
   where id = v_job_id;
  select count(*) into v_completed from public.plan_quota_reservations
   where request_id = v_job_id and status = 'completed';
  if v_completed <> 4 then
    raise exception 'Successful job did not consume image and general daily/monthly quotas';
  end if;
  select count(*) into v_reservations from public.plan_quota_events
   where reservation_id in (
     select id from public.plan_quota_reservations where request_id = v_job_id
   ) and event_type = 'completed';
  if v_reservations <> 4 then
    raise exception 'Successful job did not append all period quota completion events';
  end if;

  -- AI request concurrency is a temporary hold and must be released on success.
  select * into v_created
    from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      null,
      null,
      'ai_processing',
      'quota-test-provider',
      'quota-test-model',
      'plan-quota-ai-job-001',
      repeat('c', 64),
      '{"prompt":"AI quota test","quantity":1}'::jsonb,
      '{"amount":5,"quantity":1,"price_version":"test-v1"}'::jsonb,
      5
    );
  if jsonb_array_length(v_created.quota_reservations) <> 6 then
    raise exception 'AI request must reserve AI, general-job, and parallel dimensions';
  end if;

  -- One concurrent AI slot is available. A second active job must fail and
  -- roll back its job, hold, and the daily/monthly reservations it tentatively made.
  select count(*) into v_before_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';
  select count(*) into v_before_holds from public.credit_holds
   where user_id = '22222222-2222-4222-8222-222222222222';
  begin
    perform * from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      null, null, 'ai_processing', 'quota-test-provider', 'quota-test-model',
      'plan-quota-ai-job-overflow',
      repeat('d', 64),
      '{"prompt":"concurrency overflow","quantity":1}'::jsonb,
      '{"amount":5,"quantity":1,"price_version":"test-v1"}'::jsonb,
      5
    );
    raise exception 'Second concurrent AI job was unexpectedly admitted';
  exception when sqlstate '54000' then
    null;
  end;
  select count(*) into v_after_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';
  select count(*) into v_after_holds from public.credit_holds
   where user_id = '22222222-2222-4222-8222-222222222222';
  if v_after_jobs <> v_before_jobs or v_after_holds <> v_before_holds then
    raise exception 'Concurrent AI quota denial did not roll back job and hold';
  end if;

  update public.generation_jobs
     set status = 'succeeded', completed_at = now(), updated_at = now()
   where id = v_created.job_id;

  if (select count(*) from public.plan_quota_reservations
       where request_id = v_created.job_id and status = 'completed') <> 4
     or (select count(*) from public.plan_quota_reservations
       where request_id = v_created.job_id
         and feature_key in ('max_concurrent_ai_requests','max_parallel_jobs')
         and status = 'released') <> 2 then
    raise exception 'AI success must consume period quotas and release both concurrency slots';
  end if;

  -- Once the slot is released, a later request can enter; failure then releases
  -- all three dimensions rather than consuming period usage.
  select * into v_created
    from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      null, null, 'ai_processing', 'quota-test-provider', 'quota-test-model',
      'plan-quota-ai-job-failure',
      repeat('e', 64),
      '{"prompt":"terminal failure release","quantity":1}'::jsonb,
      '{"amount":5,"quantity":1,"price_version":"test-v1"}'::jsonb,
      5
    );
  update public.generation_jobs
     set status = 'failed', completed_at = now(), updated_at = now()
   where id = v_created.job_id;
  if (select count(*) from public.plan_quota_reservations
       where request_id = v_created.job_id and status = 'released') <> 6 then
    raise exception 'Terminal failure must release all AI and general quota dimensions';
  end if;
end;
$plan_quota_atomic_admission_test$;


-- A pending plan is not an entitlement, even when the account has credits.
insert into public.user_plan_assignments(
  id, user_id, approved_plan_version_id, assignment_source,
  source_reference, idempotency_key, status, starts_at, ends_at, created_by
) values (
  '15151515-1515-4151-8151-151515151515',
  '11111111-1111-4111-8111-111111111111',
  '13131313-1313-4131-8131-131313131313',
  'operator_grant', 'pending-only-fixture', 'pending-only-plan-001',
  'pending', now() - interval '1 minute', now() + interval '30 days',
  '22222222-2222-4222-8222-222222222222'
);
insert into public.user_plan_assignment_events(
  assignment_id, user_id, event_type, actor_user_id, event_key, reason
) values (
  '15151515-1515-4151-8151-151515151515',
  '11111111-1111-4111-8111-111111111111',
  'created',
  '22222222-2222-4222-8222-222222222222',
  'created:pending-only-fixture',
  'Pending assignment must not activate quota access'
);
select public.grant_user_credit_lot(
  '11111111-1111-4111-8111-111111111111',
  10, 'bonus', 'pending-plan-credit-test',
  'pending-plan-credit-grant-001',
  now() + interval '30 days',
  '{"test_fixture":true}'::jsonb
);

do $pending_plan_is_not_active_test$
declare
  v_jobs_before integer;
  v_jobs_after integer;
  v_wallet_before bigint;
  v_wallet_after bigint;
begin
  select count(*) into v_jobs_before from public.generation_jobs
   where user_id = '11111111-1111-4111-8111-111111111111';
  select available_credits into v_wallet_before from public.credit_wallets
   where user_id = '11111111-1111-4111-8111-111111111111';

  begin
    perform * from public.create_plan_credited_generation_job_with_outbox(
      '11111111-1111-4111-8111-111111111111',
      null, null, 'image_generation', 'quota-test-provider', 'quota-test-model',
      'pending-plan-must-not-admit',
      repeat('f', 64),
      '{"prompt":"pending plan should be denied","quantity":1}'::jsonb,
      '{"amount":5,"quantity":1,"price_version":"test-v1"}'::jsonb,
      5
    );
    raise exception 'Pending plan unexpectedly admitted a generation job';
  exception when sqlstate 'P0002' then
    null;
  end;

  select count(*) into v_jobs_after from public.generation_jobs
   where user_id = '11111111-1111-4111-8111-111111111111';
  select available_credits into v_wallet_after from public.credit_wallets
   where user_id = '11111111-1111-4111-8111-111111111111';
  if v_jobs_after <> v_jobs_before or v_wallet_after <> v_wallet_before then
    raise exception 'Pending-plan denial did not roll back job and credit reservation';
  end if;
end;
$pending_plan_is_not_active_test$;


do $media_generation_quota_unit_test$
declare
  v_job record;
  v_units integer;
begin
  select * into v_job
    from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222',
      null,
      'abababab-abab-4bab-8bab-abababababab',
      'video_generation',
      'quota-test-provider',
      'quota-test-model',
      'plan-quota-video-duration-001',
      repeat('9', 64),
      '{"prompt":"video duration is not generation count","quantity":30,"duration_seconds":30,"resolution":"1080p"}'::jsonb,
      '{"amount":30,"quantity":30,"price_version":"test-v1"}'::jsonb,
      30
    );
  select sum(reserved_units)::integer into v_units
    from public.plan_quota_reservations
   where request_id = v_job.job_id
     and feature_key in ('daily_video_generations','monthly_video_generations');
  if v_units <> 2 then
    raise exception 'Video quota must count one generation per job, not quote quantity';
  end if;
  update public.generation_jobs
     set status = 'failed', completed_at = now(), updated_at = now()
   where id = v_job.job_id;
end;
$media_generation_quota_unit_test$;


-- Video duration and resolution are validated against the immutable active plan
-- before any job, outbox event, or credit hold can be created.
do $video_plan_limits_test$
declare
  v_before_jobs integer;
  v_after_jobs integer;
  v_rejected boolean;
begin
  select count(*) into v_before_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';

  v_rejected := false;
  begin
    perform * from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222', null, null,
      'video_generation', 'quota-test-provider', 'quota-test-model',
      'video-plan-duration-overflow', repeat('a',64),
      '{"quantity":1,"duration_seconds":61,"resolution":"1080p"}'::jsonb,
      '{"amount":1,"quantity":1,"price_version":"test-v1"}'::jsonb, 1
    );
  exception when insufficient_privilege then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Video duration above the approved plan limit was accepted';
  end if;

  v_rejected := false;
  begin
    perform * from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222', null, null,
      'video_generation', 'quota-test-provider', 'quota-test-model',
      'video-plan-resolution-overflow', repeat('b',64),
      '{"quantity":1,"duration_seconds":30,"resolution":"4k"}'::jsonb,
      '{"amount":1,"quantity":1,"price_version":"test-v1"}'::jsonb, 1
    );
  exception when insufficient_privilege then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'Video resolution above the approved plan limit was accepted';
  end if;

  select count(*) into v_after_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';
  if v_after_jobs <> v_before_jobs then
    raise exception 'Rejected video limits created a job or credit hold';
  end if;
end;
$video_plan_limits_test$;


-- max_parallel_jobs is a cross-provider, cross-feature temporary reservation.
do $parallel_generation_limit_test$
declare
  v_first record;
  v_second record;
  v_third record;
  v_before_jobs integer;
  v_after_jobs integer;
  v_rejected boolean := false;
begin
  select * into v_first from public.create_plan_credited_generation_job_with_outbox(
    '22222222-2222-4222-8222-222222222222', null, null,
    'image_generation', 'quota-test-provider', 'quota-test-model',
    'parallel-job-first', repeat('c',64),
    '{"quantity":1,"prompt":"parallel first"}'::jsonb,
    '{"amount":1,"quantity":1,"price_version":"test-v1"}'::jsonb, 1
  );
  select * into v_second from public.create_plan_credited_generation_job_with_outbox(
    '22222222-2222-4222-8222-222222222222', null, null,
    'image_generation', 'quota-test-provider', 'quota-test-model',
    'parallel-job-second', repeat('d',64),
    '{"quantity":1,"prompt":"parallel second"}'::jsonb,
    '{"amount":1,"quantity":1,"price_version":"test-v1"}'::jsonb, 1
  );

  select count(*) into v_before_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';
  begin
    perform * from public.create_plan_credited_generation_job_with_outbox(
      '22222222-2222-4222-8222-222222222222', null, null,
      'image_generation', 'quota-test-provider', 'quota-test-model',
      'parallel-job-third-denied', repeat('e',64),
      '{"quantity":1,"prompt":"parallel third"}'::jsonb,
      '{"amount":1,"quantity":1,"price_version":"test-v1"}'::jsonb, 1
    );
  exception when sqlstate '54000' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'A third job exceeded the max_parallel_jobs limit';
  end if;
  select count(*) into v_after_jobs from public.generation_jobs
   where user_id = '22222222-2222-4222-8222-222222222222';
  if v_after_jobs <> v_before_jobs then
    raise exception 'Parallel-job denial did not roll back its job';
  end if;

  update public.generation_jobs
     set status = 'succeeded', completed_at = now(), updated_at = now()
   where id = v_first.job_id;

  select * into v_third from public.create_plan_credited_generation_job_with_outbox(
    '22222222-2222-4222-8222-222222222222', null, null,
    'image_generation', 'quota-test-provider', 'quota-test-model',
    'parallel-job-third-after-release', repeat('f',64),
    '{"quantity":1,"prompt":"parallel third after release"}'::jsonb,
    '{"amount":1,"quantity":1,"price_version":"test-v1"}'::jsonb, 1
  );
  if v_third.job_id is null then
    raise exception 'Released parallel slot was not reusable';
  end if;

  update public.generation_jobs
     set status = 'failed', completed_at = now(), updated_at = now()
   where id in (v_second.job_id, v_third.job_id);
  if (select count(*) from public.plan_quota_reservations
       where request_id in (v_first.job_id,v_second.job_id,v_third.job_id)
         and feature_key = 'max_parallel_jobs' and status = 'released') <> 3 then
    raise exception 'Parallel slots were not released on terminal job states';
  end if;
end;
$parallel_generation_limit_test$;


-- Feature flags in the immutable approved snapshot are enforced independently
-- of numeric quota configuration.
insert into public.plan_catalog_drafts(
  id, plan_code, plan_version, display_name, billing_period, period_days,
  credits_per_period, limits_json, features_json, created_by
) values (
  '16161616-1616-4161-8161-161616161616',
  'test_no_video', 1, 'Test No Video', 'month', 30, 1000,
  (select limits_json from public.plan_catalog_drafts
    where id = '12121212-1212-4121-8121-121212121212'),
  '["image","audio","ai"]'::jsonb,
  '11111111-1111-4111-8111-111111111111'
);
insert into public.approved_plan_versions(
  id, source_draft_id, plan_code, plan_version, display_name,
  billing_period, period_days, credits_per_period, limits_json,
  features_json, approved_by, approval_reason
) values (
  '17171717-1717-4171-8171-171717171717',
  '16161616-1616-4161-8161-161616161616',
  'test_no_video', 1, 'Test No Video', 'month', 30, 1000,
  (select limits_json from public.plan_catalog_drafts
    where id = '16161616-1616-4161-8161-161616161616'),
  '["image","audio","ai"]'::jsonb,
  '11111111-1111-4111-8111-111111111111',
  'Approved fixture without video capability'
);
insert into public.user_plan_assignments(
  id, user_id, approved_plan_version_id, assignment_source,
  source_reference, idempotency_key, status, starts_at, ends_at, created_by
) values (
  '18181818-1818-4181-8181-181818181818',
  '11111111-1111-4111-8111-111111111111',
  '17171717-1717-4171-8171-171717171717',
  'operator_grant', 'test-no-video-assignment', 'test-no-video-assignment-001',
  'pending', now() - interval '1 minute', now() + interval '30 days',
  '22222222-2222-4222-8222-222222222222'
);
insert into public.user_plan_assignment_events(
  assignment_id, user_id, event_type, actor_user_id, event_key, reason
) values (
  '18181818-1818-4181-8181-181818181818',
  '11111111-1111-4111-8111-111111111111',
  'activated',
  '22222222-2222-4222-8222-222222222222',
  'activated:test-no-video-assignment-001',
  'Test fixture activation without video feature'
);

do $plan_feature_allowlist_test$
declare
  v_before_jobs integer;
  v_after_jobs integer;
  v_rejected boolean := false;
begin
  select count(*) into v_before_jobs from public.generation_jobs
   where user_id = '11111111-1111-4111-8111-111111111111';
  begin
    perform * from public.create_plan_credited_generation_job_with_outbox(
      '11111111-1111-4111-8111-111111111111', null, null,
      'video_generation', 'quota-test-provider', 'quota-test-model',
      'plan-feature-video-not-included', repeat('a',64),
      '{"quantity":1,"duration_seconds":20,"resolution":"720p"}'::jsonb,
      '{"amount":1,"quantity":1,"price_version":"test-v1"}'::jsonb, 1
    );
  exception when insufficient_privilege then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'A video job was admitted when the approved plan excludes video';
  end if;
  select count(*) into v_after_jobs from public.generation_jobs
   where user_id = '11111111-1111-4111-8111-111111111111';
  if v_after_jobs <> v_before_jobs then
    raise exception 'Feature exclusion did not roll back generation admission';
  end if;
end;
$plan_feature_allowlist_test$;
