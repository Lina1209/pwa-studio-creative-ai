-- PWA Studio: atomic worker lifecycle primitives.
-- Database state remains authoritative. These RPCs do not start a worker or provider.
-- Apply after 0012_create_scene_generation_job_rpc.sql.

create or replace function public.claim_next_generation_job(
  p_worker_id text,
  p_lease_seconds integer default 180
)
returns table (
  job_id uuid,
  user_id uuid,
  studio_scene_id uuid,
  job_type text,
  provider text,
  model text,
  request_snapshot jsonb,
  attempt_count integer,
  max_attempts integer,
  lease_expires_at timestamptz
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'worker_id must contain 1 to 120 characters' using errcode = '22023';
  end if;
  if p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
    raise exception 'lease_seconds must be between 30 and 3600' using errcode = '22023';
  end if;

  -- Exhausted jobs whose worker disappeared become terminal instead of looping forever.
  update public.generation_jobs
     set status = 'failed',
         last_error_code = 'worker_lease_expired',
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         updated_at = now()
   where status = 'running'
     and lease_expires_at <= now()
     and attempt_count >= max_attempts;

  return query
  with candidate as (
    select j.id
      from public.generation_jobs as j
     where (
       j.status in ('queued', 'retry_wait') and j.available_at <= now()
     ) or (
       j.status = 'running' and j.lease_expires_at <= now()
     )
     order by j.available_at, j.created_at, j.id
     for update skip locked
     limit 1
  ),
  claimed as (
    update public.generation_jobs as j
       set status = 'running',
           attempt_count = j.attempt_count + 1,
           lease_owner = btrim(p_worker_id),
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           heartbeat_at = now(),
           started_at = coalesce(j.started_at, now()),
           completed_at = null,
           last_error_code = case
             when j.status = 'running' then 'worker_lease_expired'
             else j.last_error_code
           end,
           updated_at = now()
      from candidate as c
     where j.id = c.id
     returning j.id, j.user_id, j.studio_scene_id, j.job_type,
               j.provider, j.model, j.request_snapshot,
               j.attempt_count, j.max_attempts, j.lease_expires_at
  )
  select c.id, c.user_id, c.studio_scene_id, c.job_type,
         c.provider, c.model, c.request_snapshot,
         c.attempt_count, c.max_attempts, c.lease_expires_at
    from claimed as c;
end;
$$;

create or replace function public.heartbeat_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_lease_seconds integer default 180
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_updated integer;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
    raise exception 'Invalid worker identity or lease duration' using errcode = '22023';
  end if;

  update public.generation_jobs
     set heartbeat_at = now(),
         lease_expires_at = now() + make_interval(secs => p_lease_seconds),
         updated_at = now()
   where id = p_job_id
     and status = 'running'
     and lease_owner = btrim(p_worker_id)
     and lease_expires_at > now();

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

create or replace function public.retry_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_error_code text,
  p_retry_delay_seconds integer default 30
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_updated integer;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_error_code is null or p_error_code !~ '^[a-z0-9_]{1,80}$'
     or p_retry_delay_seconds is null or p_retry_delay_seconds not between 1 and 86400 then
    raise exception 'Invalid retry metadata' using errcode = '22023';
  end if;

  update public.generation_jobs
     set status = case when attempt_count >= max_attempts then 'failed' else 'retry_wait' end,
         available_at = case
           when attempt_count >= max_attempts then available_at
           else now() + make_interval(secs => p_retry_delay_seconds)
         end,
         last_error_code = p_error_code,
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = case when attempt_count >= max_attempts then now() else null end,
         updated_at = now()
   where id = p_job_id
     and status = 'running'
     and lease_owner = btrim(p_worker_id)
     and lease_expires_at > now();

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

create or replace function public.complete_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_result_storage_path text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_updated integer;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_result_storage_path is null
     or length(p_result_storage_path) not between 1 and 1024
     or left(p_result_storage_path, 1) = '/'
     or position('..' in p_result_storage_path) > 0 then
    raise exception 'Invalid completion metadata' using errcode = '22023';
  end if;

  update public.generation_jobs
     set status = 'succeeded',
         result_storage_path = p_result_storage_path,
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         updated_at = now()
   where id = p_job_id
     and status = 'running'
     and lease_owner = btrim(p_worker_id)
     and lease_expires_at > now()
     and left(p_result_storage_path, length(user_id::text) + 1) = user_id::text || '/';

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

revoke all on function public.claim_next_generation_job(text, integer) from public, anon, authenticated;
revoke all on function public.heartbeat_generation_job(uuid, text, integer) from public, anon, authenticated;
revoke all on function public.retry_generation_job(uuid, text, text, integer) from public, anon, authenticated;
revoke all on function public.complete_generation_job(uuid, text, text) from public, anon, authenticated;

grant execute on function public.claim_next_generation_job(text, integer) to service_role;
grant execute on function public.heartbeat_generation_job(uuid, text, integer) to service_role;
grant execute on function public.retry_generation_job(uuid, text, text, integer) to service_role;
grant execute on function public.complete_generation_job(uuid, text, text) to service_role;

comment on function public.claim_next_generation_job(text, integer) is
  'Atomically claims one eligible generation job with FOR UPDATE SKIP LOCKED and a bounded lease.';
comment on function public.heartbeat_generation_job(uuid, text, integer) is
  'Extends only the active, unexpired lease owned by the calling worker identity.';
comment on function public.retry_generation_job(uuid, text, text, integer) is
  'Releases an active worker lease and schedules a bounded retry, or fails after max_attempts.';
comment on function public.complete_generation_job(uuid, text, text) is
  'Marks a job successful only for its active worker and an owner-prefixed private storage path; worker must verify upload before calling.';
