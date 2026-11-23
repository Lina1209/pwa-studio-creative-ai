-- Tighten fulfillment worker boundaries: explicit lease expiry, bounded batches,
-- hard attempt ceiling, and RPC-only execution-state mutation.
alter table public.payment_fulfillment_outbox
  add column lease_expires_at timestamptz;

create or replace function public.guard_payment_fulfillment_outbox_update()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  if new.id is distinct from old.id
     or new.payment_order_id is distinct from old.payment_order_id
     or new.user_id is distinct from old.user_id
     or new.provider_code is distinct from old.provider_code
     or new.amount_minor is distinct from old.amount_minor
     or new.currency_code is distinct from old.currency_code
     or new.created_at is distinct from old.created_at then
    raise exception 'payment fulfillment purchase facts are immutable'
      using errcode = '55000';
  end if;

  if new.status is distinct from old.status
     and not (
       (old.status = 'queued' and new.status in ('processing','manual_review'))
       or (old.status = 'processing' and new.status in ('queued','completed','failed','manual_review'))
       or (old.status = 'failed' and new.status in ('queued','manual_review'))
     ) then
    raise exception 'invalid payment fulfillment status transition: % -> %', old.status, new.status
      using errcode = '23514';
  end if;

  if new.attempt_count < old.attempt_count
     or new.attempt_count > old.attempt_count + 1 then
    raise exception 'payment fulfillment attempt counter must stay or increase by one'
      using errcode = '23514';
  end if;

  if new.status = 'processing' then
    if new.lock_token is null or new.locked_at is null or new.lease_expires_at is null
       or new.lease_expires_at <= new.locked_at then
      raise exception 'processing fulfillment requires a valid bounded lease'
        using errcode = '23514';
    end if;
  elsif new.lock_token is not null or new.locked_at is not null or new.lease_expires_at is not null then
    raise exception 'non-processing fulfillment cannot retain a worker lease'
      using errcode = '23514';
  end if;

  if new.status = 'completed' then
    if old.status <> 'processing' or new.completed_at is null then
      raise exception 'completion requires a processing claim and completion timestamp'
        using errcode = '23514';
    end if;
  elsif new.completed_at is not null then
    raise exception 'only completed fulfillment may have completed_at'
      using errcode = '23514';
  end if;

  new.updated_at := now();
  return new;
end;
$$;

create or replace function public.claim_payment_fulfillment(
  p_lease_seconds integer default 120,
  p_batch_size integer default 1
)
returns table (
  fulfillment_id uuid,
  payment_order_id uuid,
  user_id uuid,
  provider_code text,
  amount_minor bigint,
  currency_code text,
  attempt_count integer,
  lease_token uuid,
  lease_expires_at timestamptz
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_lease_seconds is null or p_lease_seconds < 15 or p_lease_seconds > 900
     or p_batch_size is null or p_batch_size < 1 or p_batch_size > 20 then
    raise exception 'lease duration or batch size is outside allowed bounds'
      using errcode = '22023';
  end if;

  -- An expired final attempt is parked for human review, never reclaimed forever.
  with exhausted as (
    select o.id
      from public.payment_fulfillment_outbox o
     where o.status = 'processing'
       and o.lease_expires_at <= now()
       and o.attempt_count >= 5
     for update skip locked
  )
  update public.payment_fulfillment_outbox o
     set status = 'manual_review',
         locked_at = null,
         lock_token = null,
         lease_expires_at = null,
         last_error_code = 'lease_expired_max_attempts'
    from exhausted e
   where o.id = e.id;

  return query
  with candidates as (
    select o.id
      from public.payment_fulfillment_outbox o
     where (
       (o.status = 'queued' and o.available_at <= now() and o.attempt_count < 5)
       or (o.status = 'processing' and o.lease_expires_at <= now() and o.attempt_count < 5)
     )
     order by o.available_at, o.created_at, o.id
     for update skip locked
     limit p_batch_size
  ),
  claimed as (
    update public.payment_fulfillment_outbox o
       set status = 'processing',
           attempt_count = o.attempt_count + 1,
           locked_at = now(),
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           lock_token = gen_random_uuid(),
           last_error_code = null
      from candidates c
     where o.id = c.id
     returning o.*
  )
  select c.id, c.payment_order_id, c.user_id, c.provider_code,
         c.amount_minor, c.currency_code, c.attempt_count,
         c.lock_token, c.lease_expires_at
    from claimed c
   order by c.available_at, c.created_at, c.id;
end;
$$;

create or replace function public.complete_payment_fulfillment(
  p_fulfillment_id uuid,
  p_lease_token uuid
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_count integer;
begin
  update public.payment_fulfillment_outbox
     set status = 'completed',
         locked_at = null,
         lock_token = null,
         lease_expires_at = null,
         completed_at = now(),
         last_error_code = null
   where id = p_fulfillment_id
     and status = 'processing'
     and lock_token = p_lease_token
     and lease_expires_at > now();
  get diagnostics v_count = row_count;
  return v_count = 1;
end;
$$;

create or replace function public.fail_payment_fulfillment(
  p_fulfillment_id uuid,
  p_lease_token uuid,
  p_error_code text,
  p_retry_after_seconds integer default 60,
  p_max_attempts integer default 5
)
returns text
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_row public.payment_fulfillment_outbox%rowtype;
  v_next_status text;
begin
  if p_error_code is null or p_error_code !~ '^[a-zA-Z0-9_.:-]{1,80}$'
     or p_retry_after_seconds < 0 or p_retry_after_seconds > 86400
     or p_max_attempts < 1 or p_max_attempts > 5 then
    raise exception 'invalid fulfillment retry parameters'
      using errcode = '22023';
  end if;

  select * into v_row
    from public.payment_fulfillment_outbox
   where id = p_fulfillment_id
     and status = 'processing'
     and lock_token = p_lease_token
     and lease_expires_at > now()
   for update;

  if not found then
    return 'lease_lost';
  end if;

  if v_row.attempt_count >= p_max_attempts then
    v_next_status := 'manual_review';
  else
    v_next_status := 'queued';
  end if;

  update public.payment_fulfillment_outbox
     set status = v_next_status,
         available_at = case when v_next_status = 'queued'
           then now() + make_interval(secs => p_retry_after_seconds)
           else available_at end,
         locked_at = null,
         lock_token = null,
         lease_expires_at = null,
         last_error_code = p_error_code
   where id = p_fulfillment_id;

  return v_next_status;
end;
$$;

-- No direct mutation of execution fields: workers must use fenced RPCs.
revoke update on public.payment_fulfillment_outbox from public, anon, authenticated, service_role;
revoke all on function public.record_verified_payment_provider_event_base(text,text,uuid,text,text,bigint,text,text)
  from public, anon, authenticated, service_role;

revoke all on function public.claim_payment_fulfillment(integer,integer) from public, anon, authenticated;
revoke all on function public.complete_payment_fulfillment(uuid,uuid) from public, anon, authenticated;
revoke all on function public.fail_payment_fulfillment(uuid,uuid,text,integer,integer) from public, anon, authenticated;
grant execute on function public.claim_payment_fulfillment(integer,integer) to service_role;
grant execute on function public.complete_payment_fulfillment(uuid,uuid) to service_role;
grant execute on function public.fail_payment_fulfillment(uuid,uuid,text,integer,integer) to service_role;

comment on column public.payment_fulfillment_outbox.lease_expires_at is
  'Authoritative lease deadline; expired workers cannot complete or fail a task, even before another worker reclaims it.';
