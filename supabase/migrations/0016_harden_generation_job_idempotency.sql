-- PWA Studio: strict validation for the generic atomic job-creation RPC.
-- This hardens the existing idempotency boundary; it does not enable billing.

create or replace function public.create_generation_job_with_outbox(
  p_user_id uuid,
  p_project_id uuid,
  p_job_type text,
  p_provider text,
  p_model text,
  p_idempotency_key text,
  p_request_hash text,
  p_request_snapshot jsonb default '{}'::jsonb,
  p_pricing_snapshot jsonb default '{}'::jsonb
)
returns table (job_id uuid, event_id uuid, created boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_job_id uuid;
  v_event_id uuid;
  v_existing_hash text;
  v_existing_project_id uuid;
  v_existing_job_type text;
  v_existing_provider text;
  v_existing_model text;
begin
  if p_user_id is null then
    raise exception 'p_user_id is required' using errcode = '22023';
  end if;
  if p_job_type is null or p_job_type not in (
    'image_generation', 'video_generation', 'audio_generation',
    'speech_generation', 'ai_processing', 'media_export'
  ) then
    raise exception 'Unsupported generation job type' using errcode = '22023';
  end if;
  if p_provider is null or length(btrim(p_provider)) not between 1 and 100
     or p_model is null or length(btrim(p_model)) not between 1 and 200 then
    raise exception 'provider and model must be non-empty and within their length limits' using errcode = '22023';
  end if;
  if p_idempotency_key is null or length(p_idempotency_key) not between 8 and 200
     or p_request_hash is null or p_request_hash !~ '^[a-f0-9]{32,128}$' then
    raise exception 'Invalid idempotency key or request hash' using errcode = '22023';
  end if;
  if jsonb_typeof(coalesce(p_request_snapshot, '{}'::jsonb)) <> 'object'
     or jsonb_typeof(coalesce(p_pricing_snapshot, '{}'::jsonb)) <> 'object'
     or octet_length(coalesce(p_request_snapshot, '{}'::jsonb)::text) > 65536
     or octet_length(coalesce(p_pricing_snapshot, '{}'::jsonb)::text) > 16384 then
    raise exception 'Invalid or oversized job snapshot' using errcode = '22023';
  end if;

  insert into public.generation_jobs (
    user_id, project_id, job_type, provider, model,
    idempotency_key, request_hash, request_snapshot, pricing_snapshot
  ) values (
    p_user_id, p_project_id, p_job_type, btrim(p_provider), btrim(p_model),
    p_idempotency_key, p_request_hash,
    coalesce(p_request_snapshot, '{}'::jsonb),
    coalesce(p_pricing_snapshot, '{}'::jsonb)
  )
  on conflict (user_id, idempotency_key) do nothing
  returning id into v_job_id;

  if v_job_id is null then
    select j.id, j.request_hash, j.project_id, j.job_type, j.provider, j.model
      into v_job_id, v_existing_hash, v_existing_project_id,
           v_existing_job_type, v_existing_provider, v_existing_model
    from public.generation_jobs j
    where j.user_id = p_user_id and j.idempotency_key = p_idempotency_key
    for update;

    if not found then
      raise exception 'Idempotency conflict could not be resolved; retry the request'
        using errcode = '40001';
    end if;
    if v_existing_hash is distinct from p_request_hash
       or v_existing_project_id is distinct from p_project_id
       or v_existing_job_type is distinct from p_job_type
       or v_existing_provider is distinct from btrim(p_provider)
       or v_existing_model is distinct from btrim(p_model) then
      raise exception 'Idempotency key was already used for a different request'
        using errcode = '22023';
    end if;

    select e.event_id into v_event_id
    from public.outbox_events e
    where e.aggregate_type = 'generation_job'
      and e.aggregate_id = v_job_id
      and e.event_type = 'generation_job.created'
    order by e.id limit 1;

    -- Repair a legacy/malformed missing event without creating a second job.
    if v_event_id is null then
      insert into public.outbox_events(aggregate_type, aggregate_id, event_type, payload)
      values ('generation_job', v_job_id, 'generation_job.created',
              jsonb_build_object('job_id', v_job_id))
      returning outbox_events.event_id into v_event_id;
    end if;

    return query select v_job_id, v_event_id, false;
    return;
  end if;

  insert into public.outbox_events(aggregate_type, aggregate_id, event_type, payload)
  values ('generation_job', v_job_id, 'generation_job.created',
          jsonb_build_object('job_id', v_job_id))
  returning outbox_events.event_id into v_event_id;

  return query select v_job_id, v_event_id, true;
end;
$$;

revoke all on function public.create_generation_job_with_outbox(
  uuid, uuid, text, text, text, text, text, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.create_generation_job_with_outbox(
  uuid, uuid, text, text, text, text, text, jsonb, jsonb
) to service_role;

comment on function public.create_generation_job_with_outbox(
  uuid, uuid, text, text, text, text, text, jsonb, jsonb
) is 'Strictly validates and atomically creates an owner-scoped generation job and outbox event; idempotent per user/key.';
