-- Correct plan quota window semantics for concurrency and idempotent replay.
create or replace function public.reserve_plan_quota(
  p_user_id uuid,
  p_request_id uuid,
  p_feature_key text,
  p_operation_key text,
  p_units integer default 1
)
returns table(reservation_id uuid, assignment_id uuid, feature_limit integer,
              used_units integer, remaining_units integer, period_start timestamptz,
              status text, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_assignment public.user_plan_assignments%rowtype;
  v_plan public.approved_plan_versions%rowtype;
  v_existing public.plan_quota_reservations%rowtype;
  v_period_start timestamptz;
  v_limit_text text;
  v_limit integer;
  v_used integer;
  v_reservation_id uuid;
begin
  if p_user_id is null or p_request_id is null
     or p_feature_key is null or p_feature_key not in (
       'daily_ai_requests','monthly_ai_requests','max_concurrent_ai_requests',
       'daily_image_generations','monthly_image_generations',
       'daily_video_generations','monthly_video_generations',
       'daily_audio_generations','monthly_audio_generations'
     )
     or p_operation_key is null or char_length(p_operation_key) not between 8 and 200
     or p_units is null or p_units not between 1 and 10000 then
    raise exception 'invalid plan quota reservation parameters' using errcode = '22023';
  end if;

  v_period_start := case
    when p_feature_key = 'max_concurrent_ai_requests' then 'epoch'::timestamptz
    when p_feature_key like 'daily_%' then date_trunc('day', now() at time zone 'UTC') at time zone 'UTC'
    when p_feature_key like 'monthly_%' then date_trunc('month', now() at time zone 'UTC') at time zone 'UTC'
    else date_trunc('minute', now())
  end;

  perform pg_advisory_xact_lock(hashtextextended(
    p_user_id::text || ':' || p_feature_key || ':' || v_period_start::text, 0
  ));

  select * into v_existing
    from public.plan_quota_reservations
   where user_id = p_user_id and operation_key = p_operation_key;
  if found then
    if v_existing.request_id <> p_request_id
       or v_existing.feature_key <> p_feature_key
       or v_existing.reserved_units <> p_units then
      raise exception 'plan quota idempotency key mismatch' using errcode = '23505';
    end if;

    select apv.limits_json ->> v_existing.feature_key
      into v_limit_text
      from public.user_plan_assignments a
      join public.approved_plan_versions apv on apv.id = a.approved_plan_version_id
     where a.id = v_existing.assignment_id;
    if v_limit_text is null or v_limit_text !~ '^[0-9]{1,9}$' then
      raise exception 'original plan quota limit is unavailable' using errcode = '55000';
    end if;
    v_limit := v_limit_text::integer;

    if v_existing.feature_key = 'max_concurrent_ai_requests' then
      select coalesce(sum(r.reserved_units),0)::integer into v_used
        from public.plan_quota_reservations r
       where r.user_id = p_user_id and r.feature_key = v_existing.feature_key
         and r.period_start = v_existing.period_start and r.status = 'reserved';
    else
      select coalesce(sum(r.reserved_units),0)::integer into v_used
        from public.plan_quota_reservations r
       where r.user_id = p_user_id and r.feature_key = v_existing.feature_key
         and r.period_start = v_existing.period_start
         and r.status in ('reserved','completed');
    end if;

    return query select v_existing.id, v_existing.assignment_id, v_limit, v_used,
      greatest(v_limit-v_used,0), v_existing.period_start, v_existing.status, true;
    return;
  end if;

  select a.* into v_assignment
    from public.user_plan_assignments a
   join lateral (
     select e.event_type
       from public.user_plan_assignment_events e
      where e.assignment_id = a.id
      order by e.occurred_at desc, e.id desc
      limit 1
   ) latest_event on latest_event.event_type = 'activated'
   where a.user_id = p_user_id
     and a.starts_at <= now()
     and a.ends_at > now()
   order by a.starts_at desc
   limit 1;

  if not found then
    raise exception 'no active plan assignment' using errcode = 'P0002';
  end if;

  if (select count(*)
        from public.user_plan_assignments a
        join lateral (
          select e.event_type
            from public.user_plan_assignment_events e
           where e.assignment_id = a.id
           order by e.occurred_at desc, e.id desc
           limit 1
        ) latest_event on latest_event.event_type = 'activated'
       where a.user_id = p_user_id
         and a.starts_at <= now() and a.ends_at > now()) <> 1 then
    raise exception 'multiple active plan assignments; quota check denied' using errcode = '23514';
  end if;

  select * into v_plan from public.approved_plan_versions
   where id = v_assignment.approved_plan_version_id;
  if not found then
    raise exception 'active plan snapshot not found' using errcode = 'P0002';
  end if;

  v_limit_text := v_plan.limits_json ->> p_feature_key;
  if v_limit_text is null or v_limit_text !~ '^[0-9]{1,9}$' then
    raise exception 'feature is not included in active plan' using errcode = '42501';
  end if;
  v_limit := v_limit_text::integer;
  if v_limit <= 0 then
    raise exception 'plan quota exhausted' using errcode = '54000';
  end if;

  if p_feature_key = 'max_concurrent_ai_requests' then
    select coalesce(sum(r.reserved_units),0)::integer into v_used
      from public.plan_quota_reservations r
     where r.user_id = p_user_id and r.feature_key = p_feature_key
       and r.status = 'reserved';
  else
    select coalesce(sum(r.reserved_units),0)::integer into v_used
      from public.plan_quota_reservations r
     where r.user_id = p_user_id and r.feature_key = p_feature_key
       and r.period_start = v_period_start
       and r.status in ('reserved','completed');
  end if;

  if v_used + p_units > v_limit then
    raise exception 'plan quota exhausted' using errcode = '54000';
  end if;

  insert into public.plan_quota_reservations(
    user_id, assignment_id, request_id, feature_key, period_start,
    reserved_units, operation_key, status
  ) values (
    p_user_id, v_assignment.id, p_request_id, p_feature_key, v_period_start,
    p_units, p_operation_key, 'reserved'
  ) returning id into v_reservation_id;

  insert into public.plan_quota_events(
    reservation_id, user_id, event_type, event_key, metadata
  ) values (
    v_reservation_id, p_user_id, 'reserved',
    'reserved:' || md5(p_operation_key),
    jsonb_build_object('feature_key',p_feature_key,'units',p_units,'period_start',v_period_start)
  );

  return query select v_reservation_id, v_assignment.id, v_limit,
    v_used + p_units, greatest(v_limit-v_used-p_units,0),
    v_period_start, 'reserved'::text, false;
end;
$$;

revoke all on function public.reserve_plan_quota(uuid,uuid,text,text,integer)
  from public, anon, authenticated;
grant execute on function public.reserve_plan_quota(uuid,uuid,text,text,integer)
  to service_role;
