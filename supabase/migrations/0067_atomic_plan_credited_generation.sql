-- Allow one request to reserve multiple independent quota dimensions.
-- A generation request can consume daily + monthly usage and an AI concurrency slot.
alter table public.plan_quota_reservations
  drop constraint if exists plan_quota_reservations_user_id_request_id_key;

alter table public.plan_quota_reservations
  add constraint plan_quota_reservations_request_feature_unique
  unique (user_id, request_id, feature_key);

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
     or p_quote_snapshot ->> 'amount' !~ '^[1-9][0-9]{0,12}
    raise exception 'Credit amount does not match the signed quote snapshot'
      using errcode = '22023';
  end if;

  v_quote_quantity := p_quote_snapshot ->> 'quantity';
  if v_quote_quantity is null or v_quote_quantity !~ '^[1-9][0-9]{0,4}$'
     or v_quote_quantity::integer > 10000 then
    raise exception 'Pricing quote quantity is invalid'
      using errcode = '22023';
  end if;

  if p_job_type = 'image_generation' then
    v_features := array['daily_image_generations','monthly_image_generations'];
    v_units := v_quote_quantity::integer;
  elsif p_job_type = 'video_generation' then
    v_features := array['daily_video_generations','monthly_video_generations'];
    v_units := 1;
  elsif p_job_type in ('audio_generation','speech_generation') then
    v_features := array['daily_audio_generations','monthly_audio_generations'];
    v_units := 1;
  else
    v_features := array[
      'daily_ai_requests','monthly_ai_requests','max_concurrent_ai_requests'
    ];
    v_units := 1;
  end if;

  select * into v_job
    from public.create_credited_generation_job_with_outbox(
      p_user_id, p_project_id, p_studio_scene_id, p_job_type,
      p_provider, p_model, p_idempotency_key, p_request_hash,
      p_request_snapshot, p_quote_snapshot, p_credit_amount
    );

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

     or (p_quote_snapshot ->> 'amount')::bigint > 1000000000000
     or (p_quote_snapshot ->> 'amount')::bigint <> p_credit_amount then
    raise exception 'Credit amount does not match the signed quote snapshot'
      using errcode = '22023';
  end if;

  v_quote_quantity := p_quote_snapshot ->> 'quantity';
  if v_quote_quantity is null or v_quote_quantity !~ '^[1-9][0-9]{0,4}$'
     or v_quote_quantity::integer > 10000 then
    raise exception 'Pricing quote quantity is invalid'
      using errcode = '22023';
  end if;

  if p_job_type = 'image_generation' then
    v_features := array['daily_image_generations','monthly_image_generations'];
    v_units := v_quote_quantity::integer;
  elsif p_job_type = 'video_generation' then
    v_features := array['daily_video_generations','monthly_video_generations'];
    v_units := v_quote_quantity::integer;
  elsif p_job_type in ('audio_generation','speech_generation') then
    v_features := array['daily_audio_generations','monthly_audio_generations'];
    v_units := v_quote_quantity::integer;
  else
    v_features := array[
      'daily_ai_requests','monthly_ai_requests','max_concurrent_ai_requests'
    ];
    v_units := 1;
  end if;

  select * into v_job
    from public.create_credited_generation_job_with_outbox(
      p_user_id, p_project_id, p_studio_scene_id, p_job_type,
      p_provider, p_model, p_idempotency_key, p_request_hash,
      p_request_snapshot, p_quote_snapshot, p_credit_amount
    );

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
