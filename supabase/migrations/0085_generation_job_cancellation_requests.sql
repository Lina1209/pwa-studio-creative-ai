-- Owner-authorized generation cancellation requests.
-- Queued work can be cancelled and settled immediately. Running work is only
-- marked cancel_requested: credits remain held until a worker confirms that
-- provider execution has actually stopped.

create or replace function public.request_generation_job_cancellation(
  p_job_id uuid
)
returns table(job_status text, cancellation_action text, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_user_id uuid;
  v_job public.generation_jobs%rowtype;
  v_hold_id uuid;
begin
  v_user_id := auth.uid();
  if v_user_id is null then
    raise exception 'An authenticated owner session is required'
      using errcode = '28000';
  end if;
  if p_job_id is null then
    raise exception 'job_id is required' using errcode = '22023';
  end if;

  select * into v_job
    from public.generation_jobs
   where id = p_job_id and user_id = v_user_id
   for update;

  if not found then
    raise exception 'Generation job not found' using errcode = 'P0002';
  end if;

  if v_job.status in ('queued', 'retry_wait') then
    update public.generation_jobs
       set status = 'cancelled',
           lease_owner = null,
           lease_expires_at = null,
           heartbeat_at = null,
           completed_at = now(),
           last_error_code = 'user_cancelled',
           updated_at = now()
     where id = v_job.id;

    select h.id into v_hold_id
      from public.credit_holds h
     where h.job_id = v_job.id and h.user_id = v_user_id
       and h.status = 'held'
     for update;

    if v_hold_id is not null then
      perform public.release_job_credit_hold(
        v_user_id, v_hold_id, 'user_cancelled'
      );
    end if;

    return query select 'cancelled'::text, 'cancelled_immediately'::text, false;
    return;
  end if;

  if v_job.status = 'running' then
    update public.generation_jobs
       set status = 'cancel_requested',
           last_error_code = 'user_cancel_requested',
           updated_at = now()
     where id = v_job.id;

    return query select 'cancel_requested'::text, 'awaiting_worker_confirmation'::text, false;
    return;
  end if;

  if v_job.status = 'cancel_requested' then
    return query select 'cancel_requested'::text, 'awaiting_worker_confirmation'::text, true;
    return;
  end if;

  -- Terminal success/failure/cancellation/expiry is immutable from the
  -- customer's cancellation endpoint. In particular, success is never refunded.
  if v_job.status in ('succeeded', 'failed', 'cancelled', 'expired') then
    return query select v_job.status::text, 'already_terminal'::text, true;
    return;
  end if;

  raise exception 'Generation job has an unsupported state'
    using errcode = '55000';
end;
$$;

revoke all on function public.request_generation_job_cancellation(uuid)
  from public, anon;
grant execute on function public.request_generation_job_cancellation(uuid)
  to authenticated;

comment on function public.request_generation_job_cancellation(uuid) is
  'Owner-scoped cancellation request. Queued/retry_wait jobs are cancelled and settled atomically; running jobs remain credit-held in cancel_requested until a worker confirms provider execution has stopped.';
