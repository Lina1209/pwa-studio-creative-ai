-- Atomic queue claiming with SKIP LOCKED and expiring worker leases.
-- These RPCs only coordinate execution; they do not grant credits or activate plans.
create or replace function public.claim_payment_fulfillment(
  p_lease_seconds integer default 120
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
  if p_lease_seconds < 15 or p_lease_seconds > 900 then
    raise exception 'lease duration must be between 15 and 900 seconds'
      using errcode = '22023';
  end if;

  return query
  with candidate as (
    select o.id
      from public.payment_fulfillment_outbox o
     where (
       (o.status = 'queued' and o.available_at <= now())
       or (o.status = 'processing' and o.locked_at < now() - make_interval(secs => p_lease_seconds))
     )
     order by o.available_at, o.created_at, o.id
     for update skip locked
     limit 1
  ),
  claimed as (
    update public.payment_fulfillment_outbox o
       set status = 'processing',
           attempt_count = o.attempt_count + 1,
           locked_at = now(),
           lock_token = gen_random_uuid(),
           last_error_code = null
      from candidate c
     where o.id = c.id
     returning o.*
  )
  select c.id, c.payment_order_id, c.user_id, c.provider_code,
         c.amount_minor, c.currency_code, c.attempt_count,
         c.lock_token, c.locked_at + make_interval(secs => p_lease_seconds)
    from claimed c;
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
         completed_at = now(),
         last_error_code = null
   where id = p_fulfillment_id
     and status = 'processing'
     and lock_token = p_lease_token;
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
     or p_max_attempts < 1 or p_max_attempts > 20 then
    raise exception 'invalid fulfillment retry parameters'
      using errcode = '22023';
  end if;

  select * into v_row
    from public.payment_fulfillment_outbox
   where id = p_fulfillment_id
     and status = 'processing'
     and lock_token = p_lease_token
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
         last_error_code = p_error_code
   where id = p_fulfillment_id;

  return v_next_status;
end;
$$;

revoke all on function public.claim_payment_fulfillment(integer) from public, anon, authenticated;
revoke all on function public.complete_payment_fulfillment(uuid,uuid) from public, anon, authenticated;
revoke all on function public.fail_payment_fulfillment(uuid,uuid,text,integer,integer) from public, anon, authenticated;
grant execute on function public.claim_payment_fulfillment(integer) to service_role;
grant execute on function public.complete_payment_fulfillment(uuid,uuid) to service_role;
grant execute on function public.fail_payment_fulfillment(uuid,uuid,text,integer,integer) to service_role;

comment on function public.claim_payment_fulfillment(integer) is
  'Service-role only atomic SKIP LOCKED claim; expired processing leases are reclaimable. No purchase fulfillment side effects.';
comment on function public.complete_payment_fulfillment(uuid,uuid) is
  'Completes only the current processing lease token; stale workers cannot complete reclaimed work.';
comment on function public.fail_payment_fulfillment(uuid,uuid,text,integer,integer) is
  'Requeues with bounded delay or moves to manual_review after max attempts; requires current lease token.';
