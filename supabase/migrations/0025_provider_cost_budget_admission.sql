-- PWA Studio: fail-closed admission gate for billable provider operations.
-- A server-authored USD ceiling must be present in the immutable job pricing
-- snapshot. Actual/unknown cost evidence is never discarded or converted to zero.

create or replace function public.authorize_generation_provider_operation(
  p_job_id uuid,
  p_worker_id text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job public.generation_jobs%rowtype;
  v_budget_text text;
  v_budget numeric(20,10);
  v_known_total numeric(20,10);
  v_has_unknown boolean;
begin
  if p_job_id is null or p_worker_id is null
     or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'Invalid provider budget admission identity' using errcode = '22023';
  end if;

  select * into v_job
    from public.generation_jobs
   where id = p_job_id
   for update;

  if not found
     or v_job.status <> 'running'
     or v_job.lease_owner is distinct from btrim(p_worker_id)
     or v_job.lease_expires_at is null
     or v_job.lease_expires_at <= now() then
    return false;
  end if;

  -- Never infer a budget from customer credits or browser input. Until an
  -- operator-authored USD ceiling is present, provider execution is disabled.
  v_budget_text := v_job.pricing_snapshot ->> 'maximum_provider_cost_usd';
  if v_budget_text is null
     or v_budget_text !~ '^(0|[1-9][0-9]{0,9})([.][0-9]{1,10})?$' then
    return false;
  end if;
  v_budget := v_budget_text::numeric(20,10);

  select coalesce(sum(event.cost_usd), 0),
         coalesce(bool_or(event.cost_source = 'unknown'), false)
    into v_known_total, v_has_unknown
    from public.generation_provider_cost_events as event
   where event.job_id = p_job_id;

  -- Unknown cost means the remaining budget cannot be proven safe. A new
  -- billable request is denied; existing cost events remain immutable.
  if v_has_unknown or v_known_total >= v_budget then
    return false;
  end if;

  return true;
end;
$$;

revoke all on function public.authorize_generation_provider_operation(uuid, text)
  from public, anon, authenticated;
grant execute on function public.authorize_generation_provider_operation(uuid, text)
  to service_role;

comment on function public.authorize_generation_provider_operation(uuid, text) is
  'Fail-closed admission for billable provider calls: requires an active lease, explicit server-authored USD cap, and complete known costs below that cap.';
