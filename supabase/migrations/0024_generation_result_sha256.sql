-- PWA Studio: persist verified result integrity in the authoritative job row.
-- Database-only change. Does not enable production workers, providers, billing, or deployment.

alter table public.generation_jobs
  add column if not exists result_sha256 text;

do $$
begin
  if not exists (
    select 1 from pg_constraint
     where conrelid = 'public.generation_jobs'::regclass
       and conname = 'generation_jobs_result_sha256_format'
  ) then
    alter table public.generation_jobs
      add constraint generation_jobs_result_sha256_format
      check (result_sha256 is null or result_sha256 ~ '^[0-9a-f]{64}$');
  end if;
end;
$$;

create or replace function public.complete_credited_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_result_storage_path text,
  p_result_sha256 text
)
returns table(completed boolean, replayed boolean,
              available_credits bigint, reserved_credits bigint)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_hold public.credit_holds%rowtype;
  v_wallet public.credit_wallets%rowtype;
  v_entry public.credit_ledger%rowtype;
begin
  if p_job_id is null
     or p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_result_storage_path is null
     or length(p_result_storage_path) not between 1 and 1024
     or left(p_result_storage_path, 1) = '/'
     or position('..' in p_result_storage_path) > 0
     or p_result_sha256 is null or p_result_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'Invalid credited completion parameters' using errcode = '22023';
  end if;

  select * into v_job from public.generation_jobs
   where id = p_job_id for update;
  if not found then raise exception 'Generation job not found' using errcode = 'P0002'; end if;

  -- A repeated completion is accepted only when the exact result path and
  -- captured hold are already recorded; it never mutates balances a second time.
  if v_job.status = 'succeeded' then
    if v_job.result_storage_path is distinct from p_result_storage_path
       or v_job.result_sha256 is distinct from p_result_sha256 then
      raise exception 'Completed job result path does not match replay' using errcode = '22023';
    end if;
    select * into v_hold from public.credit_holds
     where job_id = p_job_id and user_id = v_job.user_id;
    if not found or v_hold.status <> 'captured' then
      raise exception 'Successful credited job is missing its captured hold' using errcode = '55000';
    end if;
    select * into v_entry from public.credit_ledger
     where hold_id = v_hold.id and operation_type = 'capture';
    if not found then
      raise exception 'Successful credited job is missing its capture ledger entry' using errcode = '55000';
    end if;
    select * into v_wallet from public.credit_wallets
     where user_id = v_job.user_id;
    return query select true, true, v_wallet.available_credits, v_wallet.reserved_credits;
    return;
  end if;

  if v_job.status <> 'running'
     or v_job.lease_owner is distinct from btrim(p_worker_id)
     or v_job.lease_expires_at is null or v_job.lease_expires_at <= now()
     or left(p_result_storage_path, length(v_job.user_id::text) + 1)
          <> v_job.user_id::text || '/' then
    return query select false, false, null::bigint, null::bigint;
    return;
  end if;

  select * into v_hold from public.credit_holds
   where job_id = p_job_id and user_id = v_job.user_id
   for update;
  if not found or v_hold.status <> 'held' then
    raise exception 'Active credited generation job has no held credit reservation'
      using errcode = '55000';
  end if;

  select * into v_wallet from public.credit_wallets
   where user_id = v_job.user_id for update;
  if not found or v_wallet.reserved_credits < v_hold.amount then
    raise exception 'Wallet reserved balance is inconsistent with the credit hold'
      using errcode = '23514';
  end if;

  update public.credit_wallets as wallet
     set reserved_credits = wallet.reserved_credits - v_hold.amount,
         updated_at = now()
   where wallet.id = v_wallet.id
   returning wallet.* into v_wallet;

  update public.credit_holds
     set status = 'captured', captured_at = now(), updated_at = now()
   where id = v_hold.id;

  insert into public.credit_ledger(
    user_id, hold_id, operation_type, operation_key,
    delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, metadata
  ) values (
    v_job.user_id, v_hold.id, 'capture', 'capture:' || v_hold.operation_key,
    0, -v_hold.amount,
    v_wallet.available_credits, v_wallet.reserved_credits,
    jsonb_build_object('job_id', p_job_id, 'result_storage_path', p_result_storage_path)
  );

  update public.generation_jobs
     set status = 'succeeded',
         result_storage_path = p_result_storage_path,
         result_sha256 = p_result_sha256,
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         updated_at = now()
   where id = p_job_id;

  return query select true, false, v_wallet.available_credits, v_wallet.reserved_credits;
end;
$$;

-- Remove the legacy path-only RPC so callers cannot bypass the integrity binding.
drop function if exists public.complete_credited_generation_job(uuid, text, text);
revoke all on function public.complete_credited_generation_job(uuid, text, text, text)
  from public, anon, authenticated;
grant execute on function public.complete_credited_generation_job(uuid, text, text, text)
  to service_role;

comment on column public.generation_jobs.result_sha256 is
  'Lowercase SHA-256 of the exact verified private result object bytes; null only for legacy/non-completed jobs.';
comment on function public.complete_credited_generation_job(uuid, text, text, text) is
  'Atomically captures held credits and records the exact private result path plus verified SHA-256; caller must verify the private uploaded bytes before invoking.';
