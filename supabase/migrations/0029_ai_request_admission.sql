-- Distributed per-user admission control for synchronous AI endpoints.
-- This is an operational safety gate, not a customer billing/credit ledger.
create table if not exists public.ai_request_admission_windows (
  user_id uuid not null,
  window_start timestamptz not null,
  request_count integer not null default 0 check (request_count >= 0),
  primary key (user_id, window_start)
);

create table if not exists public.ai_request_admission_reservations (
  request_id uuid primary key,
  user_id uuid not null,
  endpoint text not null check (endpoint in ('chat', 'prompts')),
  state text not null default 'reserved'
    check (state in ('reserved', 'completed', 'released')),
  reserved_at timestamptz not null default now(),
  finished_at timestamptz
);

create index if not exists ai_request_admission_active_user_idx
  on public.ai_request_admission_reservations(user_id, reserved_at)
  where state = 'reserved';

alter table public.ai_request_admission_windows enable row level security;
alter table public.ai_request_admission_reservations enable row level security;
revoke all on public.ai_request_admission_windows from public, anon, authenticated;
revoke all on public.ai_request_admission_reservations from public, anon, authenticated;
grant all on public.ai_request_admission_windows to service_role;
grant all on public.ai_request_admission_reservations to service_role;

create or replace function public.reserve_ai_request(
  p_user_id uuid,
  p_request_id uuid,
  p_endpoint text,
  p_max_per_minute integer default 10,
  p_max_concurrent integer default 2,
  p_max_global_concurrent integer default 16
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
  v_existing public.ai_request_admission_reservations%rowtype;
begin
  if p_user_id is null or p_request_id is null
     or p_endpoint is null or p_endpoint not in ('chat', 'prompts')
     or p_max_per_minute not between 1 and 120
     or p_max_concurrent not between 1 and 16
     or p_max_global_concurrent not between 1 and 128 then
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

create or replace function public.finish_ai_request(
  p_user_id uuid,
  p_request_id uuid,
  p_outcome text
)
returns boolean
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_state text;
begin
  if p_user_id is null or p_request_id is null
     or p_outcome not in ('completed', 'released') then
    raise exception 'Invalid AI admission completion';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));

  select state into v_state
    from public.ai_request_admission_reservations
   where request_id = p_request_id and user_id = p_user_id
   for update;

  if not found then
    return false;
  end if;
  if v_state <> 'reserved' then
    return v_state = p_outcome;
  end if;

  update public.ai_request_admission_reservations
     set state = p_outcome, finished_at = now()
   where request_id = p_request_id and user_id = p_user_id;
  return true;
end;
$$;

revoke all on function public.reserve_ai_request(uuid, uuid, text, integer, integer, integer)
  from public, anon, authenticated;
revoke all on function public.finish_ai_request(uuid, uuid, text)
  from public, anon, authenticated;
grant execute on function public.reserve_ai_request(uuid, uuid, text, integer, integer)
  to service_role;
grant execute on function public.finish_ai_request(uuid, uuid, text)
  to service_role;

comment on table public.ai_request_admission_reservations is
  'Operational per-user AI request admission state; not a credit ledger or billing record.';
