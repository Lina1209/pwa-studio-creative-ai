-- Resolve plan quota reservations in the same transaction as job terminalization.
-- Successful generation consumes period quotas but releases its concurrency slot.
-- Failed/cancelled/expired jobs release every reservation.

create or replace function public.resolve_generation_job_plan_quotas()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_reservation record;
  v_outcome text;
begin
  if old.status is not distinct from new.status
     or new.status not in ('succeeded','failed','cancelled','expired') then
    return new;
  end if;

  for v_reservation in
    select id, user_id, feature_key, operation_key, status
      from public.plan_quota_reservations
     where user_id = new.user_id
       and request_id = new.id
       and status = 'reserved'
     order by id
     for update
  loop
    if new.status = 'succeeded'
       and v_reservation.feature_key <> 'max_concurrent_ai_requests' then
      v_outcome := 'completed';
    else
      v_outcome := 'released';
    end if;

    update public.plan_quota_reservations
       set status = v_outcome,
           finished_at = now()
     where id = v_reservation.id;

    insert into public.plan_quota_events(
      reservation_id, user_id, event_type, event_key, metadata
    ) values (
      v_reservation.id,
      new.user_id,
      v_outcome,
      v_outcome || ':' || md5(v_reservation.operation_key),
      jsonb_build_object(
        'job_id', new.id,
        'job_terminal_status', new.status,
        'feature_key', v_reservation.feature_key
      )
    );
  end loop;

  return new;
end;
$$;

revoke all on function public.resolve_generation_job_plan_quotas()
  from public, anon, authenticated, service_role;

drop trigger if exists generation_job_plan_quota_terminal
  on public.generation_jobs;
create trigger generation_job_plan_quota_terminal
after update of status on public.generation_jobs
for each row
execute function public.resolve_generation_job_plan_quotas();

comment on function public.resolve_generation_job_plan_quotas() is
  'Internal trigger: resolves all customer-plan quota holds atomically with terminal job state. Success consumes daily/monthly usage and releases concurrency; failure releases all usage.';
