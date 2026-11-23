-- Enforce general generation counts, parallel-job caps, and video constraints.
-- The admission path remains inert unless the existing generation feature flag is enabled.

alter table public.plan_quota_reservations
  drop constraint if exists plan_quota_reservations_feature_key_check;
alter table public.plan_quota_reservations
  add constraint plan_quota_reservations_feature_key_check
  check (feature_key in (
    'daily_ai_requests','monthly_ai_requests','max_concurrent_ai_requests',
    'daily_image_generations','monthly_image_generations',
    'daily_video_generations','monthly_video_generations',
    'daily_audio_generations','monthly_audio_generations',
    'daily_generation_jobs','monthly_generation_jobs','max_parallel_jobs'
  ));

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
  v_required_feature text;
begin
  if p_user_id is null or p_request_id is null
     or p_feature_key is null or p_feature_key not in (
       'daily_ai_requests','monthly_ai_requests','max_concurrent_ai_requests',
       'daily_image_generations','monthly_image_generations',
       'daily_video_generations','monthly_video_generations',
       'daily_audio_generations','monthly_audio_generations',
       'daily_generation_jobs','monthly_generation_jobs','max_parallel_jobs'
     )
     or p_operation_key is null or char_length(p_operation_key) not between 8 and 200
     or p_units is null or p_units not between 1 and 10000 then
    raise exception 'invalid plan quota reservation parameters' using errcode = '22023';
  end if;

  v_period_start := case
    when p_feature_key in ('max_concurrent_ai_requests','max_parallel_jobs') then 'epoch'::timestamptz
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

    if v_existing.feature_key in ('max_concurrent_ai_requests','max_parallel_jobs') then
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

  v_required_feature := case
    when p_feature_key in ('daily_ai_requests','monthly_ai_requests','max_concurrent_ai_requests') then 'ai'
    when p_feature_key in ('daily_image_generations','monthly_image_generations') then 'image'
    when p_feature_key in ('daily_video_generations','monthly_video_generations') then 'video'
    when p_feature_key in ('daily_audio_generations','monthly_audio_generations') then 'audio'
    else null
  end;
  if v_required_feature is not null and not (v_plan.features_json ? v_required_feature) then
    raise exception 'feature is not included in the active plan' using errcode = '42501';
  end if;

  v_limit_text := v_plan.limits_json ->> p_feature_key;
  if v_limit_text is null or v_limit_text !~ '^[0-9]{1,9}$' then
    raise exception 'feature is not included in active plan' using errcode = '42501';
  end if;
  v_limit := v_limit_text::integer;
  if v_limit <= 0 then
    raise exception 'plan quota exhausted' using errcode = '54000';
  end if;

  if p_feature_key in ('max_concurrent_ai_requests','max_parallel_jobs') then
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

create or replace function public.create_plan_credited_generation_job_with_outbox(
  p_user_id uuid,
  p_project_id uuid,
  p_studio_scene_id uuid,
  p_job_type text,
  p_provider text,
  p_model text,
  p_idempotency_key text,
  p_request_hash text,
  p_request_snapshot jsonb,
  p_quote_snapshot jsonb,
  p_credit_amount bigint
)
returns table(
  job_id uuid,
  event_id uuid,
  hold_id uuid,
  available_credits bigint,
  reserved_credits bigint,
  created boolean,
  replayed boolean,
  quota_reservations jsonb
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job record;
  v_feature text;
  v_units integer;
  v_features text[];
  v_quota record;
  v_quota_results jsonb := '[]'::jsonb;
  v_quote_quantity text;
  v_plan public.approved_plan_versions%rowtype;
  v_active_assignment_count integer;
  v_required_feature text;
  v_video_seconds integer;
  v_max_video_seconds integer;
  v_video_resolution text;
  v_max_resolution text;
  v_video_resolution_rank integer;
  v_max_resolution_rank integer;
begin
  if p_job_type not in (
    'image_generation','video_generation','audio_generation',
    'speech_generation','ai_processing'
  ) then
    raise exception 'This job type has no approved customer-plan quota mapping'
      using errcode = '42501';
  end if;
  if p_quote_snapshot is null
     or jsonb_typeof(p_quote_snapshot) <> 'object'
     or p_quote_snapshot ->> 'amount' is null
     or p_quote_snapshot ->> 'amount' !~ '^[1-9][0-9]{0,12}$'
     or (p_quote_snapshot ->> 'amount')::bigint > 1000000000000
     or (p_quote_snapshot ->> 'amount')::bigint <> p_credit_amount then
    raise exception 'Credit amount does not match the signed quote snapshot'
      using errcode = '22023';
  end if;

  if p_request_snapshot is null or jsonb_typeof(p_request_snapshot) <> 'object' then
    raise exception 'Generation request snapshot must be an object'
      using errcode = '22023';
  end if;

  v_quote_quantity := p_quote_snapshot ->> 'quantity';
  if v_quote_quantity is null or v_quote_quantity !~ '^[1-9][0-9]{0,4}$'
     or v_quote_quantity::integer > 10000 then
    raise exception 'Pricing quote quantity is invalid'
      using errcode = '22023';
  end if;

  v_required_feature := case
    when p_job_type = 'image_generation' then 'image'
    when p_job_type = 'video_generation' then 'video'
    when p_job_type in ('audio_generation','speech_generation') then 'audio'
    when p_job_type = 'ai_processing' then 'ai'
    else null
  end;

  if p_job_type = 'image_generation' then
    v_features := array[
      'daily_image_generations','monthly_image_generations',
      'daily_generation_jobs','monthly_generation_jobs','max_parallel_jobs'
    ];
    v_units := v_quote_quantity::integer;
  elsif p_job_type = 'video_generation' then
    v_features := array[
      'daily_video_generations','monthly_video_generations',
      'daily_generation_jobs','monthly_generation_jobs','max_parallel_jobs'
    ];
    v_units := 1;
  elsif p_job_type in ('audio_generation','speech_generation') then
    v_features := array[
      'daily_audio_generations','monthly_audio_generations',
      'daily_generation_jobs','monthly_generation_jobs','max_parallel_jobs'
    ];
    v_units := 1;
  else
    v_features := array[
      'daily_ai_requests','monthly_ai_requests','max_concurrent_ai_requests',
      'daily_generation_jobs','monthly_generation_jobs','max_parallel_jobs'
    ];
    v_units := 1;
  end if;

  select * into v_job
    from public.create_credited_generation_job_with_outbox(
      p_user_id, p_project_id, p_studio_scene_id, p_job_type,
      p_provider, p_model, p_idempotency_key, p_request_hash,
      p_request_snapshot, p_quote_snapshot, p_credit_amount
    );

  -- A valid idempotent replay must remain readable after its original plan expires.
  -- The base RPC verifies the original request, quote, hold and outbox identity.
  -- Require the complete original quota set before replaying; never create new
  -- quota reservations for a pre-existing non-plan job.
  if v_job.replayed then
    if (select count(*) from public.plan_quota_reservations r
         where r.user_id = p_user_id
           and r.request_id = v_job.job_id
           and r.feature_key = any(v_features)
           and r.operation_key = 'quota:' || md5(p_idempotency_key) || ':' || r.feature_key)
       <> cardinality(v_features) then
      raise exception 'Existing plan-based generation job is missing quota reservations'
        using errcode = '55000';
    end if;
  else
    select count(*)::integer into v_active_assignment_count
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
       and a.ends_at > now();
  
    if v_active_assignment_count = 0 then
      raise exception 'no active plan assignment' using errcode = 'P0002';
    elsif v_active_assignment_count <> 1 then
      raise exception 'multiple active plan assignments; generation denied'
        using errcode = '23514';
    end if;
  
    select apv.*
      into v_plan
      from public.user_plan_assignments a
      join lateral (
        select e.event_type
          from public.user_plan_assignment_events e
         where e.assignment_id = a.id
         order by e.occurred_at desc, e.id desc
         limit 1
      ) latest_event on latest_event.event_type = 'activated'
      join public.approved_plan_versions apv
        on apv.id = a.approved_plan_version_id
     where a.user_id = p_user_id
       and a.starts_at <= now()
       and a.ends_at > now()
     limit 1;
  
    if not (v_plan.features_json ? v_required_feature) then
      raise exception 'feature is not included in the active plan'
        using errcode = '42501';
    end if;
  
    if p_job_type = 'video_generation' then
      v_max_video_seconds := nullif(v_plan.limits_json ->> 'max_video_seconds','')::integer;
      if v_max_video_seconds is not null then
        if coalesce(p_request_snapshot ->> 'duration_seconds','') !~ '^[1-9][0-9]{0,5}
  foreach v_feature in array v_features loop
    select * into v_quota
      from public.reserve_plan_quota(
        p_user_id,
        v_job.job_id,
        v_feature,
        'quota:' || md5(p_idempotency_key) || ':' || v_feature,
        case when v_feature = 'max_concurrent_ai_requests' then 1 else v_units end
      );

    v_quota_results := v_quota_results || jsonb_build_array(jsonb_build_object(
      'reservation_id', v_quota.reservation_id,
      'feature_key', v_feature,
      'feature_limit', v_quota.feature_limit,
      'used_units', v_quota.used_units,
      'remaining_units', v_quota.remaining_units,
      'status', v_quota.status,
      'replayed', v_quota.replayed
    ));
  end loop;

  return query select v_job.job_id, v_job.event_id, v_job.hold_id,
    v_job.available_credits, v_job.reserved_credits,
    v_job.created, v_job.replayed, v_quota_results;
end;
$$;

revoke all on function public.create_plan_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) from public, anon, authenticated;
grant execute on function public.create_plan_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) to service_role;

comment on function public.create_plan_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) is
  'Atomically creates a durable generation job, transactional outbox event, lot-aware credit hold, and all required customer-plan quota reservations. Any failed step rolls back the entire submission.';

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
       and v_reservation.feature_key not in ('max_concurrent_ai_requests','max_parallel_jobs') then
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
 then
          raise exception 'Video duration must be a positive integer number of seconds'
            using errcode = '22023';
        end if;
        v_video_seconds := (p_request_snapshot ->> 'duration_seconds')::integer;
        if v_video_seconds > v_max_video_seconds then
          raise exception 'Video duration exceeds the active plan limit'
            using errcode = '42501';
        end if;
      end if;
  
      v_max_resolution := v_plan.limits_json ->> 'max_resolution';
      if v_max_resolution is not null then
        v_video_resolution := p_request_snapshot ->> 'resolution';
        v_video_resolution_rank := case v_video_resolution
          when '480p' then 1 when '720p' then 2
          when '1080p' then 3 when '4k' then 4 else null end;
        v_max_resolution_rank := case v_max_resolution
          when '480p' then 1 when '720p' then 2
          when '1080p' then 3 when '4k' then 4 else null end;
        if v_video_resolution_rank is null or v_max_resolution_rank is null then
          raise exception 'Video resolution is missing or unsupported'
            using errcode = '22023';
        end if;
        if v_video_resolution_rank > v_max_resolution_rank then
          raise exception 'Video resolution exceeds the active plan limit'
            using errcode = '42501';
        end if;
      end if;
    end if;
  
  
  end if;

  foreach v_feature in array v_features loop
    select * into v_quota
      from public.reserve_plan_quota(
        p_user_id,
        v_job.job_id,
        v_feature,
        'quota:' || md5(p_idempotency_key) || ':' || v_feature,
        case when v_feature = 'max_concurrent_ai_requests' then 1 else v_units end
      );

    v_quota_results := v_quota_results || jsonb_build_array(jsonb_build_object(
      'reservation_id', v_quota.reservation_id,
      'feature_key', v_feature,
      'feature_limit', v_quota.feature_limit,
      'used_units', v_quota.used_units,
      'remaining_units', v_quota.remaining_units,
      'status', v_quota.status,
      'replayed', v_quota.replayed
    ));
  end loop;

  return query select v_job.job_id, v_job.event_id, v_job.hold_id,
    v_job.available_credits, v_job.reserved_credits,
    v_job.created, v_job.replayed, v_quota_results;
end;
$$;

revoke all on function public.create_plan_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) from public, anon, authenticated;
grant execute on function public.create_plan_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) to service_role;

comment on function public.create_plan_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) is
  'Atomically creates a durable generation job, transactional outbox event, lot-aware credit hold, and all required customer-plan quota reservations. Any failed step rolls back the entire submission.';

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
       and v_reservation.feature_key not in ('max_concurrent_ai_requests','max_parallel_jobs') then
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
