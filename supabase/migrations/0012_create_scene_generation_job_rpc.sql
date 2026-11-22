-- PWA Studio: atomic creation of scene-bound generation jobs.
-- Apply after 0011_link_generation_jobs_to_movie_scenes.sql.
-- Studio projects are intentionally not mapped to public.projects: the job's
-- scene relationship is validated against studio_scenes and enforced by 0011's FK.

create or replace function public.create_scene_generation_job_with_outbox(
  p_user_id uuid,
  p_studio_scene_id uuid,
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
  v_existing_scene_id uuid;
  v_existing_job_type text;
  v_existing_provider text;
  v_existing_model text;
begin
  if p_user_id is null or p_studio_scene_id is null then
    raise exception 'user_id and studio_scene_id are required' using errcode = '22023';
  end if;
  if p_job_type not in ('image_generation', 'video_generation', 'audio_generation',
                        'speech_generation', 'ai_processing', 'media_export') then
    raise exception 'Unsupported generation job type' using errcode = '22023';
  end if;
  if p_provider is null or length(btrim(p_provider)) not between 1 and 100
     or p_model is null or length(btrim(p_model)) not between 1 and 200 then
    raise exception 'provider and model must be non-empty and within their length limits' using errcode = '22023';
  end if;
  if p_idempotency_key is null or length(p_idempotency_key) not between 8 and 200
     or p_request_hash is null or length(p_request_hash) not between 32 and 128 then
    raise exception 'Invalid idempotency key or request hash' using errcode = '22023';
  end if;
  if jsonb_typeof(coalesce(p_request_snapshot, '{}'::jsonb)) <> 'object'
     or jsonb_typeof(coalesce(p_pricing_snapshot, '{}'::jsonb)) <> 'object'
     or octet_length(coalesce(p_request_snapshot, '{}'::jsonb)::text) > 65536
     or octet_length(coalesce(p_pricing_snapshot, '{}'::jsonb)::text) > 16384 then
    raise exception 'Invalid or oversized job snapshot' using errcode = '22023';
  end if;

  -- Explicit preflight gives a clear error; the composite FK remains the final
  -- race-safe ownership guarantee if the scene changes concurrently.
  if not exists (
    select 1 from public.studio_scenes s
    where s.id = p_studio_scene_id and s.user_id = p_user_id
  ) then
    raise exception 'Scene was not found for this user' using errcode = '23503';
  end if;

  insert into public.generation_jobs (
    user_id, studio_scene_id, job_type, provider, model,
    idempotency_key, request_hash, request_snapshot, pricing_snapshot
  ) values (
    p_user_id, p_studio_scene_id, p_job_type, btrim(p_provider), btrim(p_model),
    p_idempotency_key, p_request_hash,
    coalesce(p_request_snapshot, '{}'::jsonb), coalesce(p_pricing_snapshot, '{}'::jsonb)
  )
  on conflict (user_id, idempotency_key) do nothing
  returning id into v_job_id;

  if v_job_id is null then
    select j.id, j.request_hash, j.studio_scene_id, j.job_type, j.provider, j.model
      into v_job_id, v_existing_hash, v_existing_scene_id,
           v_existing_job_type, v_existing_provider, v_existing_model
    from public.generation_jobs j
    where j.user_id = p_user_id and j.idempotency_key = p_idempotency_key
    for update;

    if not found then
      raise exception 'Idempotency conflict could not be resolved; retry the request'
        using errcode = '40001';
    end if;
    if v_existing_hash is distinct from p_request_hash
       or v_existing_scene_id is distinct from p_studio_scene_id
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
    return query select v_job_id, v_event_id, false;
    return;
  end if;

  insert into public.outbox_events (aggregate_type, aggregate_id, event_type, payload)
  values ('generation_job', v_job_id, 'generation_job.created',
          jsonb_build_object('job_id', v_job_id, 'studio_scene_id', p_studio_scene_id))
  returning outbox_events.event_id into v_event_id;

  return query select v_job_id, v_event_id, true;
end;
$$;

revoke all on function public.create_scene_generation_job_with_outbox(
  uuid, uuid, text, text, text, text, text, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.create_scene_generation_job_with_outbox(
  uuid, uuid, text, text, text, text, text, jsonb, jsonb
) to service_role;

comment on function public.create_scene_generation_job_with_outbox(
  uuid, uuid, text, text, text, text, text, jsonb, jsonb
) is 'Atomically creates a user-owned scene-bound generation job and outbox event.';
