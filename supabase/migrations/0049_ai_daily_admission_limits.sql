-- Add rolling 24-hour AI request ceilings in addition to per-minute and concurrency gates.
-- These are hard operational request limits, not a claim about provider USD billing.
create or replace function public.reserve_ai_request(
  p_user_id uuid,
  p_request_id uuid,
  p_endpoint text,
  p_max_per_minute integer default 10,
  p_max_concurrent integer default 2,
  p_max_global_concurrent integer default 16,
  p_max_per_day integer default 100,
  p_max_global_per_day integer default 2000
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_window timestamptz := date_trunc('minute', now());
  v_count integer;
  v_active integer;
  v_global_active integer;
  v_user_daily integer;
  v_global_daily integer;
  v_existing public.ai_request_admission_reservations%rowtype;
begin
  if p_user_id is null or p_request_id is null
     or p_endpoint is null or p_endpoint not in ('chat', 'prompts', 'movie_script', 'movie_director', 'movie_storyboard')
     or p_max_per_minute is null or p_max_per_minute not between 1 and 120
     or p_max_concurrent is null or p_max_concurrent not between 1 and 16
     or p_max_global_concurrent is null or p_max_global_concurrent not between 1 and 128
     or p_max_per_day is null or p_max_per_day not between 1 and 10000
     or p_max_global_per_day is null or p_max_global_per_day not between 1 and 100000 then
    raise exception 'Invalid AI admission request';
  end if;

  -- Serialize per-user and global admission decisions across API replicas.
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  perform pg_advisory_xact_lock(918273645);

  select * into v_existing
    from public.ai_request_admission_reservations
   where request_id = p_request_id;

  if found then
    if v_existing.user_id <> p_user_id or v_existing.endpoint <> p_endpoint then
      raise exception 'AI request idempotency conflict';
    end if;
    return jsonb_build_object(
      'admitted', v_existing.state = 'reserved',
      'duplicate', true,
      'state', v_existing.state,
      'retry_after_seconds', 10
    );
  end if;

  delete from public.ai_request_admission_reservations
   where reserved_at < now() - interval '2 days';
  delete from public.ai_request_admission_windows
   where window_start < now() - interval '2 days';

  select coalesce(request_count, 0) into v_count
    from public.ai_request_admission_windows
   where user_id = p_user_id and window_start = v_window;
  v_count := coalesce(v_count, 0);

  if v_count >= p_max_per_minute then
    return jsonb_build_object(
      'admitted', false, 'reason', 'rate_limited',
      'retry_after_seconds', 60
    );
  end if;

  select count(*)::integer into v_active
    from public.ai_request_admission_reservations
   where user_id = p_user_id
     and state = 'reserved'
     and reserved_at >= now() - interval '10 minutes';

  if v_active >= p_max_concurrent then
    return jsonb_build_object(
      'admitted', false, 'reason', 'concurrency_limited',
      'retry_after_seconds', 10
    );
  end if;

  select count(*)::integer into v_global_active
    from public.ai_request_admission_reservations
   where state = 'reserved'
     and reserved_at >= now() - interval '10 minutes';

  if v_global_active >= p_max_global_concurrent then
    return jsonb_build_object(
      'admitted', false, 'reason', 'global_concurrency_limited',
      'retry_after_seconds', 10
    );
  end if;

  select count(*)::integer into v_user_daily
    from public.ai_request_admission_reservations
   where user_id = p_user_id
     and reserved_at >= now() - interval '24 hours';

  if v_user_daily >= p_max_per_day then
    return jsonb_build_object(
      'admitted', false, 'reason', 'daily_user_limit',
      'retry_after_seconds', 300
    );
  end if;

  select count(*)::integer into v_global_daily
    from public.ai_request_admission_reservations
   where reserved_at >= now() - interval '24 hours';

  if v_global_daily >= p_max_global_per_day then
    return jsonb_build_object(
      'admitted', false, 'reason', 'daily_global_limit',
      'retry_after_seconds', 300
    );
  end if;

  insert into public.ai_request_admission_windows(user_id, window_start, request_count)
  values (p_user_id, v_window, 1)
  on conflict (user_id, window_start) do update
    set request_count = public.ai_request_admission_windows.request_count + 1;

  insert into public.ai_request_admission_reservations(
    request_id, user_id, endpoint, state, reserved_at
  ) values (p_request_id, p_user_id, p_endpoint, 'reserved', now());

  return jsonb_build_object('admitted', true, 'duplicate', false, 'state', 'reserved');
end;
$$;


revoke all on function public.reserve_ai_request(uuid, uuid, text, integer, integer, integer, integer, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_ai_request(uuid, uuid, text, integer, integer, integer, integer, integer)
  to service_role;

-- Remove the previous overload so no server caller can bypass daily limits.
drop function if exists public.reserve_ai_request(uuid, uuid, text, integer, integer, integer);
