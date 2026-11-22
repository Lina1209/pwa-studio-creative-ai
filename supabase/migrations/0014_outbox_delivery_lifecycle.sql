-- PWA Studio: durable outbox delivery leases and bounded retries.
-- This migration adds database primitives only; it does not deploy a dispatcher.
-- Apply after 0013_generation_job_worker_lifecycle.sql.

alter table public.outbox_events
  add column if not exists lease_owner text,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists max_delivery_attempts integer not null default 12,
  add column if not exists failed_at timestamptz;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.outbox_events'::regclass
      and conname = 'outbox_events_delivery_attempt_limit'
  ) then
    alter table public.outbox_events
      add constraint outbox_events_delivery_attempt_limit
      check (max_delivery_attempts between 1 and 50);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.outbox_events'::regclass
      and conname = 'outbox_events_lease_consistency'
  ) then
    alter table public.outbox_events
      add constraint outbox_events_lease_consistency
      check ((lease_owner is null) = (lease_expires_at is null));
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.outbox_events'::regclass
      and conname = 'outbox_events_terminal_consistency'
  ) then
    alter table public.outbox_events
      add constraint outbox_events_terminal_consistency
      check (
        (published_at is null or (failed_at is null and lease_owner is null))
        and (failed_at is null or (published_at is null and lease_owner is null))
      );
  end if;
end;
$$;

drop index if exists public.outbox_events_pending_idx;
create index outbox_events_pending_idx
  on public.outbox_events(available_at, id)
  where published_at is null and failed_at is null;

create index if not exists outbox_events_expired_lease_idx
  on public.outbox_events(lease_expires_at)
  where published_at is null and failed_at is null and lease_owner is not null;

create or replace function public.claim_next_outbox_event(
  p_worker_id text,
  p_lease_seconds integer default 120
)
returns table (
  event_id uuid,
  aggregate_id uuid,
  event_type text,
  payload jsonb,
  delivery_attempts integer,
  lease_expires_at timestamptz
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'worker_id must contain 1 to 120 characters' using errcode = '22023';
  end if;
  if p_lease_seconds is null or p_lease_seconds not between 30 and 3600 then
    raise exception 'lease_seconds must be between 30 and 3600' using errcode = '22023';
  end if;

  update public.outbox_events as expired
     set failed_at = now(),
         last_error_code = 'delivery_attempts_exhausted',
         lease_owner = null,
         lease_expires_at = null
   where expired.published_at is null
     and expired.failed_at is null
     and expired.lease_expires_at <= now()
     and expired.delivery_attempts >= expired.max_delivery_attempts;

  return query
  with candidate as (
    select e.id
      from public.outbox_events as e
     where e.published_at is null
       and e.failed_at is null
       and e.available_at <= now()
       and e.delivery_attempts < e.max_delivery_attempts
       and (e.lease_expires_at is null or e.lease_expires_at <= now())
     order by e.available_at, e.id
     for update skip locked
     limit 1
  ),
  claimed as (
    update public.outbox_events as e
       set delivery_attempts = e.delivery_attempts + 1,
           lease_owner = btrim(p_worker_id),
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           last_error_code = case
             when e.lease_owner is not null then 'outbox_lease_expired'
             else e.last_error_code
           end
      from candidate as c
     where e.id = c.id
     returning e.event_id, e.aggregate_id, e.event_type, e.payload,
               e.delivery_attempts, e.lease_expires_at
  )
  select c.event_id, c.aggregate_id, c.event_type, c.payload,
         c.delivery_attempts, c.lease_expires_at
    from claimed as c;
end;
$$;

create or replace function public.mark_outbox_event_published(
  p_event_id uuid,
  p_worker_id text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_updated integer;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120 then
    raise exception 'Invalid worker identity' using errcode = '22023';
  end if;

  update public.outbox_events
     set published_at = now(),
         lease_owner = null,
         lease_expires_at = null,
         last_error_code = null
   where event_id = p_event_id
     and published_at is null
     and failed_at is null
     and lease_owner = btrim(p_worker_id)
     and lease_expires_at > now();

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

create or replace function public.retry_outbox_event(
  p_event_id uuid,
  p_worker_id text,
  p_error_code text,
  p_retry_delay_seconds integer default 30
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_updated integer;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 120
     or p_error_code is null or p_error_code !~ '^[a-z0-9_]{1,80}$'
     or p_retry_delay_seconds is null or p_retry_delay_seconds not between 1 and 86400 then
    raise exception 'Invalid outbox retry metadata' using errcode = '22023';
  end if;

  update public.outbox_events
     set failed_at = case
           when delivery_attempts >= max_delivery_attempts then now()
           else null
         end,
         available_at = case
           when delivery_attempts >= max_delivery_attempts then available_at
           else now() + make_interval(secs => p_retry_delay_seconds)
         end,
         last_error_code = p_error_code,
         lease_owner = null,
         lease_expires_at = null
   where event_id = p_event_id
     and published_at is null
     and failed_at is null
     and lease_owner = btrim(p_worker_id)
     and lease_expires_at > now();

  get diagnostics v_updated = row_count;
  return v_updated = 1;
end;
$$;

revoke all on function public.claim_next_outbox_event(text, integer) from public, anon, authenticated;
revoke all on function public.mark_outbox_event_published(uuid, text) from public, anon, authenticated;
revoke all on function public.retry_outbox_event(uuid, text, text, integer) from public, anon, authenticated;

grant execute on function public.claim_next_outbox_event(text, integer) to service_role;
grant execute on function public.mark_outbox_event_published(uuid, text) to service_role;
grant execute on function public.retry_outbox_event(uuid, text, text, integer) to service_role;

comment on function public.claim_next_outbox_event(text, integer) is
  'Atomically leases one pending outbox event using FOR UPDATE SKIP LOCKED and a bounded delivery attempt count.';
comment on function public.mark_outbox_event_published(uuid, text) is
  'Marks an outbox event delivered only for its active, unexpired lease owner.';
comment on function public.retry_outbox_event(uuid, text, text, integer) is
  'Releases an active outbox lease and schedules retry, or dead-letters after max_delivery_attempts.';
