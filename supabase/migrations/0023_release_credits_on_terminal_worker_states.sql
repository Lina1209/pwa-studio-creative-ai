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
declare
  v_expired_job record;
  v_hold_id uuid;
  v_hold_status text;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'worker_id must contain 1 to 120 characters' using errcode = '22023';
  end if;
  if p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
    raise exception 'lease_seconds must be between 30 and 3600' using errcode = '22023';
  end if;

  -- Exhausted jobs are terminalized and their held credits released atomically.
  for v_expired_job in
    update public.generation_jobs as expired
       set status = 'failed',
           last_error_code = 'worker_lease_expired',
           lease_owner = null,
           lease_expires_at = null,
           heartbeat_at = null,
           completed_at = now(),
           updated_at = now()
     where expired.status = 'running'
       and expired.lease_expires_at <= now()
       and expired.attempt_count >= expired.max_attempts
     returning expired.id, expired.user_id
  loop
    select h.id, h.status into v_hold_id, v_hold_status
      from public.credit_holds h
     where h.job_id = v_expired_job.id and h.user_id = v_expired_job.user_id;
    if found and v_hold_status = 'held' then
      perform public.release_job_credit_hold(
        v_expired_job.user_id, v_hold_id, 'worker_lease_expired'
      );
    elsif found and v_hold_status not in ('released') then
      raise exception 'Expired generation job has an inconsistent credit hold'
        using errcode = '55000';
    end if;
  end loop;

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

create or replace function public.fail_generation_job(
  p_job_id uuid,
  p_worker_id text,
  p_error_code text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_updated integer;
  v_user_id uuid;
  v_hold_id uuid;
  v_hold_status text;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_error_code is null or p_error_code !~ '^[a-z0-9_]{1,80}$' then
    raise exception 'Invalid terminal failure metadata' using errcode = '22023';
  end if;

  update public.generation_jobs
     set status = 'failed',
         last_error_code = p_error_code,
         lease_owner = null,
         lease_expires_at = null,
         heartbeat_at = null,
         completed_at = now(),
         updated_at = now()
   where id = p_job_id
     and status = 'running'
     and lease_owner = btrim(p_worker_id)
     and lease_expires_at > now()
  returning user_id into v_user_id;

  get diagnostics v_updated = row_count;
  if v_updated = 1 then
    select h.id, h.status into v_hold_id, v_hold_status
      from public.credit_holds h
     where h.job_id = p_job_id and h.user_id = v_user_id;
    if found and v_hold_status = 'held' then
      perform public.release_job_credit_hold(v_user_id, v_hold_id, 'terminal_failure');
    elsif found and v_hold_status not in ('released') then
      raise exception 'Failed generation job has an inconsistent credit hold'
        using errcode = '55000';
    end if;
  end if;
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
  v_user_id uuid;
  v_status text;
  v_hold_id uuid;
  v_hold_status text;
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
     and lease_expires_at > now()
  returning user_id, status into v_user_id, v_status;

  get diagnostics v_updated = row_count;
  if v_updated = 1 and v_status = 'failed' then
    select h.id, h.status into v_hold_id, v_hold_status
      from public.credit_holds h
     where h.job_id = p_job_id and h.user_id = v_user_id;
    if found and v_hold_status = 'held' then
      perform public.release_job_credit_hold(v_user_id, v_hold_id, 'max_attempts_exceeded');
    elsif found and v_hold_status not in ('released') then
      raise exception 'Exhausted generation job has an inconsistent credit hold'
        using errcode = '55000';
    end if;
  end if;
  return v_updated = 1;
end;
$$;

revoke all on function public.claim_next_generation_job(text, integer) from public, anon, authenticated;
revoke all on function public.fail_generation_job(uuid, text, text) from public, anon, authenticated;
revoke all on function public.retry_generation_job(uuid, text, text, integer) from public, anon, authenticated;
grant execute on function public.claim_next_generation_job(text, integer) to service_role;
grant execute on function public.fail_generation_job(uuid, text, text) to service_role;
grant execute on function public.retry_generation_job(uuid, text, text, integer) to service_role;

comment on function public.claim_next_generation_job(text, integer) is
  'Claims one eligible job with SKIP LOCKED; terminalizes exhausted expired leases and atomically releases any held credits.';
comment on function public.fail_generation_job(uuid, text, text) is
  'Fails only the active lease owner and atomically releases a held credit reservation.';
comment on function public.retry_generation_job(uuid, text, text, integer) is
  'Schedules retry for an active lease; on exhausted attempts, fails and atomically releases held credits.';
