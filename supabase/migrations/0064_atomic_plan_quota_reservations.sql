-- PWA Studio: atomic plan quota reservations.
-- This is separate from operational AI admission limits and the credit ledger.
-- It requires exactly one already-active assignment; pending assignments never qualify.

create table if not exists public.plan_quota_reservations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete restrict,
  assignment_id uuid not null references public.user_plan_assignments(id) on delete restrict,
  request_id uuid not null,
  feature_key text not null check (feature_key in (
    'daily_ai_requests','monthly_ai_requests','max_concurrent_ai_requests',
    'daily_image_generations','monthly_image_generations',
    'daily_video_generations','monthly_video_generations',
    'daily_audio_generations','monthly_audio_generations'
  )),
  period_start timestamptz not null,
  reserved_units integer not null default 1 check (reserved_units between 1 and 10000),
  operation_key text not null check (char_length(operation_key) between 8 and 200),
  status text not null default 'reserved'
    check (status in ('reserved','completed','released')),
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  unique(user_id, operation_key),
  unique(user_id, request_id),
  check ((status = 'reserved' and finished_at is null)
      or (status in ('completed','released') and finished_at is not null))
);

create index if not exists plan_quota_reservations_window_idx
  on public.plan_quota_reservations(user_id, feature_key, period_start, status);

alter table public.plan_quota_reservations enable row level security;
revoke all on public.plan_quota_reservations from public, anon, authenticated;
grant select, insert, update on public.plan_quota_reservations to service_role;

create table if not exists public.plan_quota_events (
  id bigint generated always as identity primary key,
  reservation_id uuid not null references public.plan_quota_reservations(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  event_type text not null check (event_type in ('reserved','completed','released')),
  event_key text not null check (char_length(event_key) between 8 and 220),
  occurred_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(metadata) = 'object' and octet_length(metadata::text) <= 4096),
  unique(reservation_id, event_key)
);

alter table public.plan_quota_events enable row level security;
revoke all on public.plan_quota_events from public, anon, authenticated;
grant select, insert on public.plan_quota_events to service_role;

create or replace function public.prevent_plan_quota_event_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'Plan quota events are append-only'
    using errcode = '55000';
end;
$$;

drop trigger if exists plan_quota_events_immutable on public.plan_quota_events;
create trigger plan_quota_events_immutable
before update or delete on public.plan_quota_events
for each row execute function public.prevent_plan_quota_event_mutation();

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
    select count(*)::integer into v_used
      from public.plan_quota_reservations
     where user_id = p_user_id and feature_key = p_feature_key
       and period_start = v_existing.period_start
       and status in ('reserved','completed');
    select (apv.limits_json ->> p_feature_key)::text
      into v_limit_text
      from public.approved_plan_versions apv
     where apv.id = v_existing.assignment_id;
    -- Return the immutable original reservation result, not a new reservation.
    return query select v_existing.id, v_existing.assignment_id,
      coalesce(nullif(v_limit_text,'')::integer,0), v_used,
      greatest(coalesce(nullif(v_limit_text,'')::integer,0)-v_used,0),
      v_existing.period_start, v_existing.status, true;
    return;
  end if;

  select a.* into v_assignment
    from public.user_plan_assignments a
   where a.user_id = p_user_id
     and a.status = 'active'
     and a.starts_at <= now()
     and a.ends_at > now()
   order by a.starts_at desc
   limit 2;

  if not found then
    raise exception 'no active plan assignment' using errcode = 'P0002';
  end if;

  if (select count(*) from public.user_plan_assignments a
       where a.user_id = p_user_id and a.status = 'active'
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

  select coalesce(sum(r.reserved_units),0)::integer into v_used
    from public.plan_quota_reservations r
   where r.user_id = p_user_id and r.feature_key = p_feature_key
     and r.period_start = v_period_start
     and r.status in ('reserved','completed');

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
    v_used + p_units, greatest(v_limit - v_used - p_units,0),
    v_period_start, 'reserved'::text, false;
end;
$$;

create or replace function public.finish_plan_quota_reservation(
  p_user_id uuid,
  p_reservation_id uuid,
  p_outcome text
)
returns table(status text, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_row public.plan_quota_reservations%rowtype;
begin
  if p_user_id is null or p_reservation_id is null
     or p_outcome not in ('completed','released') then
    raise exception 'invalid plan quota completion parameters' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':' || p_reservation_id::text, 0));
  select * into v_row from public.plan_quota_reservations
   where id = p_reservation_id and user_id = p_user_id for update;
  if not found then
    raise exception 'plan quota reservation not found' using errcode = 'P0002';
  end if;

  if v_row.status <> 'reserved' then
    if v_row.status = p_outcome then
      return query select v_row.status, true;
      return;
    end if;
    raise exception 'plan quota reservation is already terminal' using errcode = '55000';
  end if;

  update public.plan_quota_reservations
     set status = p_outcome, finished_at = now()
   where id = v_row.id;

  insert into public.plan_quota_events(
    reservation_id, user_id, event_type, event_key, metadata
  ) values (
    v_row.id, p_user_id, p_outcome,
    p_outcome || ':' || md5(v_row.operation_key),
    jsonb_build_object('feature_key',v_row.feature_key,'units',v_row.reserved_units)
  );

  return query select p_outcome, false;
end;
$$;

revoke all on function public.reserve_plan_quota(uuid,uuid,text,text,integer)
  from public, anon, authenticated;
revoke all on function public.finish_plan_quota_reservation(uuid,uuid,text)
  from public, anon, authenticated;
grant execute on function public.reserve_plan_quota(uuid,uuid,text,text,integer)
  to service_role;
grant execute on function public.finish_plan_quota_reservation(uuid,uuid,text)
  to service_role;

comment on table public.plan_quota_reservations is
  'Atomic customer-plan quota reservations. Counts reserved and completed units; released reservations do not consume quota. Separate from operational AI admission and credit balances.';
comment on function public.reserve_plan_quota(uuid,uuid,text,text,integer) is
  'Service-role only. Requires exactly one active assignment and an explicit numeric feature limit; pending plans and missing limits fail closed.';
