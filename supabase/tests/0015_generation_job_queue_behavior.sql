-- Disposable LOCAL Supabase behavior test for migrations 0012, 0013 and 0014.
-- Run only against a fresh local/test Supabase database, never production.
-- The transaction is rolled back. It creates temporary Auth users and test rows.
-- This script tests sequential behavior; it does NOT simulate concurrent sessions.

begin;

do $$
declare
  v_owner_a uuid := gen_random_uuid();
  v_owner_b uuid := gen_random_uuid();
  v_job_success uuid := gen_random_uuid();
  v_job_retry uuid := gen_random_uuid();
  v_job_recovery uuid := gen_random_uuid();
  v_job_cancel uuid := gen_random_uuid();
  v_job_cancel_queued uuid := gen_random_uuid();
  v_job_cancel_expired uuid := gen_random_uuid();
  v_job_other_owner uuid := gen_random_uuid();
  v_asset_a uuid := gen_random_uuid();
  v_asset_b uuid := gen_random_uuid();
  v_token uuid;
  v_outbox_token uuid;
  v_outbox_id bigint;
  v_status text;
  v_ok boolean;
  v_count integer;
begin
  -- Auth fixtures are rolled back with this test transaction.
  insert into auth.users (id, email)
  values
    (v_owner_a, 'queue-test-' || v_owner_a::text || '@example.invalid'),
    (v_owner_b, 'queue-test-' || v_owner_b::text || '@example.invalid');

  insert into public.generation_jobs (id, owner_id, idempotency_key, request_fingerprint, job_type)
  values
    (v_job_success, v_owner_a, 'test-success-0001', repeat('a',64), 'image'),
    (v_job_retry, v_owner_a, 'test-retry-00001', repeat('b',64), 'image'),
    (v_job_recovery, v_owner_a, 'test-recovery-001', repeat('c',64), 'video'),
    (v_job_cancel, v_owner_a, 'test-cancel-00001', repeat('d',64), 'image'),
    (v_job_cancel_queued, v_owner_a, 'test-cancel-queue1', repeat('e',64), 'image'),
    (v_job_cancel_expired, v_owner_a, 'test-cancel-expired', repeat('1',64), 'image'),
    (v_job_other_owner, v_owner_b, 'test-other-owner1', repeat('f',64), 'image');

  insert into public.media_assets (id, owner_id, file_name, file_type, storage_path)
  values
    (v_asset_a, v_owner_a, 'owner-a-result.png', 'image/png', v_owner_a::text || '/test/owner-a-result.png'),
    (v_asset_b, v_owner_b, 'owner-b-result.png', 'image/png', v_owner_b::text || '/test/owner-b-result.png');

  -- Keep unrelated jobs out of the claim pool so each assertion targets
  -- exactly the job named in that test section.
  update public.generation_jobs
  set next_attempt_at = now() + interval '1 day'
  where id <> v_job_success;

  -- A job cannot be completed using another user's media asset.
  select j.lease_token into v_token
  from public.claim_generation_job('queue-test-worker', 120) j
  where j.id = v_job_success;
  if v_token is null then raise exception 'TEST FAILED: success job was not claimed'; end if;

  select public.complete_generation_job(v_job_success, v_token, v_asset_b, 0.001) into v_ok;
  if v_ok then raise exception 'TEST FAILED: cross-owner result asset was accepted'; end if;

  select public.complete_generation_job(v_job_success, v_token, v_asset_a, 0.001) into v_ok;
  if not v_ok then raise exception 'TEST FAILED: owner-matched result asset was rejected'; end if;

  select status into v_status from public.generation_jobs where id = v_job_success;
  if v_status <> 'succeeded' then raise exception 'TEST FAILED: success status not persisted'; end if;

  -- A completed job rejects a stale/replayed worker completion.
  select public.complete_generation_job(v_job_success, v_token, v_asset_a, 0.001) into v_ok;
  if v_ok then raise exception 'TEST FAILED: stale completion was accepted'; end if;

  -- Retryable failure transitions to retry_wait and inserts an outbox event.
  update public.generation_jobs set next_attempt_at = null where id = v_job_retry;
  select j.lease_token into v_token
  from public.claim_generation_job('queue-test-worker', 120) j
  where j.id = v_job_retry;
  select public.fail_generation_job(v_job_retry, v_token, 'temporary_provider_error', true, 5, 0.002)
    into v_status;
  if v_status <> 'retry_wait' then raise exception 'TEST FAILED: retry transition failed'; end if;
  if not exists (select 1 from public.generation_job_outbox where job_id = v_job_retry and event_type = 'job_retry_ready') then
    raise exception 'TEST FAILED: retry outbox event missing';
  end if;

  -- A worker cannot cancel another owner's job by guessing its UUID.
  select public.request_generation_job_cancel(v_job_other_owner, v_owner_a) into v_status;
  if v_status <> 'not_found' then raise exception 'TEST FAILED: cross-owner cancellation was not denied'; end if;

  -- Queued cancellation is terminal and does not require a worker lease.
  select public.request_generation_job_cancel(v_job_cancel_queued, v_owner_a) into v_status;
  if v_status <> 'cancelled' then raise exception 'TEST FAILED: queued cancellation failed'; end if;

  -- Active cancellation is fenced by the current lease token.
  update public.generation_jobs set next_attempt_at = null where id = v_job_cancel;
  select j.lease_token into v_token
  from public.claim_generation_job('queue-test-worker', 120) j
  where j.id = v_job_cancel;
  select public.request_generation_job_cancel(v_job_cancel, v_owner_a) into v_status;
  if v_status <> 'cancel_requested' then raise exception 'TEST FAILED: active cancel request failed'; end if;
  select public.finish_generation_job_cancel(v_job_cancel, v_token) into v_ok;
  if not v_ok then raise exception 'TEST FAILED: matching worker could not finish cancellation'; end if;
  select status into v_status from public.generation_jobs where id = v_job_cancel;
  if v_status <> 'cancelled' then raise exception 'TEST FAILED: cancellation terminal state missing'; end if;

  -- An expired worker cannot finish a cancellation after its lease deadline,
  -- even before the recovery process rotates/clears the fencing token.
  update public.generation_jobs set next_attempt_at = null where id = v_job_cancel_expired;
  select j.lease_token into v_token
  from public.claim_generation_job('queue-test-worker-expiring', 120) j
  where j.id = v_job_cancel_expired;
  if v_token is null then raise exception 'TEST FAILED: expiring cancel job was not claimed'; end if;
  select public.request_generation_job_cancel(v_job_cancel_expired, v_owner_a) into v_status;
  if v_status <> 'cancel_requested' then raise exception 'TEST FAILED: expiring cancel request failed'; end if;
  update public.generation_jobs set lease_expires_at = now() - interval '1 second'
  where id = v_job_cancel_expired and lease_token = v_token;
  select public.finish_generation_job_cancel(v_job_cancel_expired, v_token) into v_ok;
  if v_ok then raise exception 'TEST FAILED: expired worker finished cancellation'; end if;
  select public.recover_expired_generation_jobs(10) into v_count;
  select status into v_status from public.generation_jobs where id = v_job_cancel_expired;
  if v_status <> 'cancelled' then raise exception 'TEST FAILED: expired cancellation was not recovered'; end if;

  -- Expired worker lease is recovered to retry_wait when attempts remain.
  update public.generation_jobs set next_attempt_at = null where id = v_job_recovery;
  select j.lease_token into v_token
  from public.claim_generation_job('queue-test-worker', 120) j
  where j.id = v_job_recovery;
  update public.generation_jobs
  set lease_expires_at = now() - interval '1 second'
  where id = v_job_recovery and lease_token = v_token;
  select public.recover_expired_generation_jobs(10) into v_count;
  if v_count < 1 then raise exception 'TEST FAILED: expired lease was not recovered'; end if;
  select status into v_status from public.generation_jobs where id = v_job_recovery;
  if v_status <> 'retry_wait' then raise exception 'TEST FAILED: expired lease did not enter retry_wait'; end if;

  -- Reclaim the recovered job with a fresh token. Every operation from the
  -- previous worker must be rejected after the lease has been replaced.
  update public.generation_jobs set next_attempt_at = null where id = v_job_recovery;
  select j.lease_token into v_outbox_token
  from public.claim_generation_job('queue-test-worker-new', 120) j
  where j.id = v_job_recovery;
  if v_outbox_token is null or v_outbox_token = v_token then
    raise exception 'TEST FAILED: recovered job did not receive a fresh lease token';
  end if;
  select public.heartbeat_generation_job(v_job_recovery, v_token, 120) into v_ok;
  if v_ok then raise exception 'TEST FAILED: stale worker heartbeat was accepted'; end if;
  select public.complete_generation_job(v_job_recovery, v_token, v_asset_a, 0.001) into v_ok;
  if v_ok then raise exception 'TEST FAILED: stale worker completion was accepted'; end if;
  select public.fail_generation_job(v_job_recovery, v_token, 'stale_worker', true, 5, 0.001)
    into v_status;
  if v_status <> 'stale_lease' then raise exception 'TEST FAILED: stale worker failure was accepted'; end if;
  select lease_token into v_token from public.generation_jobs where id = v_job_recovery;
  if v_token <> v_outbox_token then
    raise exception 'TEST FAILED: stale worker changed the current lease token';
  end if;

  -- Outbox claim/ack is fenced; a replayed acknowledgement must fail.
  insert into public.generation_job_outbox(job_id, event_type)
  values (v_job_success, 'job_queued')
  returning id into v_outbox_id;
  select c.claim_token into v_outbox_token
  from public.claim_generation_outbox('queue-test-dispatcher', 100, 60) c
  where c.outbox_id = v_outbox_id;
  if v_outbox_token is null then raise exception 'TEST FAILED: outbox event was not claimed'; end if;
  select public.ack_generation_outbox(v_outbox_id, v_outbox_token) into v_ok;
  if not v_ok then raise exception 'TEST FAILED: current outbox claim was not acknowledged'; end if;
  select public.ack_generation_outbox(v_outbox_id, v_outbox_token) into v_ok;
  if v_ok then raise exception 'TEST FAILED: duplicate outbox acknowledgement was accepted'; end if;

  -- An expired outbox lease is reclaimed with a fresh token. The prior
  -- dispatcher cannot acknowledge the event after the token is rotated.
  insert into public.generation_job_outbox(job_id, event_type)
  values (v_job_success, 'job_queued')
  returning id into v_outbox_id;
  select c.claim_token into v_token
  from public.claim_generation_outbox('queue-test-dispatcher-old', 100, 60) c
  where c.outbox_id = v_outbox_id;
  if v_token is null then raise exception 'TEST FAILED: outbox event was not initially claimed'; end if;
  update public.generation_job_outbox
  set claimed_at = now() - interval '2 minutes'
  where id = v_outbox_id and claim_token = v_token;
  select c.claim_token into v_outbox_token
  from public.claim_generation_outbox('queue-test-dispatcher-new', 100, 60) c
  where c.outbox_id = v_outbox_id;
  if v_outbox_token is null or v_outbox_token = v_token then
    raise exception 'TEST FAILED: expired outbox claim did not receive a fresh token';
  end if;
  select public.ack_generation_outbox(v_outbox_id, v_token) into v_ok;
  if v_ok then raise exception 'TEST FAILED: stale outbox acknowledgement was accepted'; end if;
  select public.ack_generation_outbox(v_outbox_id, v_outbox_token) into v_ok;
  if not v_ok then raise exception 'TEST FAILED: current outbox claim could not be acknowledged'; end if;

  -- Events that have exhausted the delivery limit are dead-lettered, not claimed again.
  insert into public.generation_job_outbox(job_id, event_type, delivery_attempts)
  values (v_job_success, 'job_queued', 20)
  returning id into v_outbox_id;
  select count(*) into v_count
  from public.claim_generation_outbox('queue-test-dispatcher', 100, 60)
  where outbox_id = v_outbox_id;
  if v_count <> 0 then raise exception 'TEST FAILED: exhausted outbox event was claimed'; end if;
  if not exists (select 1 from public.generation_job_outbox where id = v_outbox_id and dead_lettered_at is not null) then
    raise exception 'TEST FAILED: exhausted outbox event was not dead-lettered';
  end if;

  raise notice 'PASS: generation job queue sequential behavior checks completed';
end;
$$;

rollback;
