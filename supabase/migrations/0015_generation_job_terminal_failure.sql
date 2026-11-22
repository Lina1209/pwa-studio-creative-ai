-- PWA Studio: explicit terminal failure for non-retryable worker errors.
-- Database primitive only; no worker or provider is activated.

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
     and lease_expires_at > now();

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

revoke all on function public.fail_generation_job(uuid, text, text) from public, anon, authenticated;
grant execute on function public.fail_generation_job(uuid, text, text) to service_role;

comment on function public.fail_generation_job(uuid, text, text) is
  'Moves a job to terminal failed state only for its active, unexpired lease owner; stores a safe error code, never raw provider text.';
