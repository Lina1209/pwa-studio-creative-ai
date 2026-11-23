-- PWA Studio: immutable refund intents and verified provider refund events.
-- This migration records provider-confirmed refunds and queues entitlement
-- compensation for explicit review. It does NOT call providers or claw back
-- credits/revoke subscriptions automatically.

create table public.payment_refunds (
  id uuid primary key default gen_random_uuid(),
  payment_order_id uuid not null references public.payment_orders(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  provider_code text not null check (provider_code ~ '^[a-z][a-z0-9_]{1,39}$'),
  amount_minor bigint not null check (amount_minor > 0),
  currency_code text not null check (currency_code ~ '^[A-Z]{3}$'),
  idempotency_key text not null check (char_length(idempotency_key) between 8 and 200),
  reason_code text not null check (reason_code ~ '^[a-z0-9_]{1,64}$'),
  status text not null default 'requested'
    check (status in ('requested','submitted','succeeded','failed','cancelled')),
  provider_refund_id text,
  requested_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  submitted_at timestamptz,
  settled_at timestamptz,
  closed_at timestamptz,
  unique(payment_order_id, idempotency_key),
  unique(provider_code, provider_refund_id),
  constraint payment_refund_status_shape check (
    (status = 'requested' and submitted_at is null and settled_at is null and closed_at is null)
    or (status = 'submitted' and submitted_at is not null and settled_at is null and closed_at is null)
    or (status = 'succeeded' and settled_at is not null and closed_at is null)
    or (status in ('failed','cancelled') and closed_at is not null and settled_at is null)
  )
);

create index payment_refunds_order_status_idx
  on public.payment_refunds(payment_order_id, status, created_at, id);
create index payment_refunds_user_timeline_idx
  on public.payment_refunds(user_id, created_at desc, id desc);

create table public.payment_refund_provider_events (
  id uuid primary key default gen_random_uuid(),
  provider_code text not null check (provider_code ~ '^[a-z][a-z0-9_]{1,39}$'),
  provider_event_id text not null check (char_length(provider_event_id) between 1 and 240),
  refund_id uuid not null references public.payment_refunds(id) on delete restrict,
  event_type text not null check (event_type in (
    'refund.pending','refund.succeeded','refund.failed','refund.cancelled'
  )),
  payload_sha256 text not null check (payload_sha256 ~ '^[a-f0-9]{64}$'),
  amount_minor bigint not null check (amount_minor > 0),
  currency_code text not null check (currency_code ~ '^[A-Z]{3}$'),
  provider_refund_id text not null check (char_length(provider_refund_id) between 1 and 240),
  signature_verified boolean not null check (signature_verified = true),
  received_at timestamptz not null default now(),
  unique(provider_code, provider_event_id)
);

create index payment_refund_provider_events_refund_idx
  on public.payment_refund_provider_events(refund_id, received_at, id);

create table public.payment_refund_events (
  id uuid primary key default gen_random_uuid(),
  refund_id uuid not null references public.payment_refunds(id) on delete restrict,
  actor_type text not null check (actor_type in ('user','admin','provider','system')),
  actor_user_id uuid references auth.users(id) on delete restrict,
  event_type text not null check (char_length(event_type) between 1 and 120),
  previous_status text,
  new_status text not null check (new_status in ('requested','submitted','succeeded','failed','cancelled')),
  event_key text not null check (char_length(event_key) between 8 and 220),
  reason_code text not null check (reason_code ~ '^[a-z0-9_]{1,64}$'),
  occurred_at timestamptz not null default now(),
  unique(refund_id, event_key)
);

create index payment_refund_events_timeline_idx
  on public.payment_refund_events(refund_id, occurred_at, id);

-- A successful money refund always creates a separate entitlement-compensation
-- work item. It stays pending until a reviewed, source-aware compensating action
-- is implemented. This table is deliberately not directly writable by clients.
create table public.payment_refund_reconciliations (
  id uuid primary key default gen_random_uuid(),
  refund_id uuid not null unique references public.payment_refunds(id) on delete restrict,
  payment_order_id uuid not null references public.payment_orders(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  purchase_type text not null check (purchase_type in ('credit_pack','subscription')),
  amount_minor bigint not null check (amount_minor > 0),
  currency_code text not null check (currency_code ~ '^[A-Z]{3}$'),
  status text not null default 'pending_review'
    check (status in ('pending_review','manual_review','compensated')),
  created_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by uuid references auth.users(id) on delete restrict,
  resolution_code text check (
    resolution_code is null or resolution_code ~ '^[a-z0-9_]{1,64}$'
  ),
  constraint payment_refund_reconciliation_resolution_shape check (
    (status = 'pending_review' and reviewed_at is null and reviewed_by is null and resolution_code is null)
    or (status = 'manual_review' and reviewed_at is not null and reviewed_by is not null and resolution_code is not null)
    or (status = 'compensated' and reviewed_at is not null and reviewed_by is not null and resolution_code is not null)
  )
);

create index payment_refund_reconciliations_queue_idx
  on public.payment_refund_reconciliations(status, created_at, id);

create or replace function public.guard_payment_refund_update()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  if new.payment_order_id is distinct from old.payment_order_id
     or new.user_id is distinct from old.user_id
     or new.provider_code is distinct from old.provider_code
     or new.amount_minor is distinct from old.amount_minor
     or new.currency_code is distinct from old.currency_code
     or new.idempotency_key is distinct from old.idempotency_key
     or new.reason_code is distinct from old.reason_code
     or new.requested_by is distinct from old.requested_by
     or new.created_at is distinct from old.created_at then
    raise exception 'refund identity and amount are immutable' using errcode = '23514';
  end if;
  if old.status in ('succeeded','failed','cancelled') then
    raise exception 'terminal refund records are immutable' using errcode = '55000';
  end if;
  if new.status is distinct from old.status and not (
    (old.status = 'requested' and new.status in ('submitted','succeeded','failed','cancelled'))
    or (old.status = 'submitted' and new.status in ('succeeded','failed','cancelled'))
  ) then
    raise exception 'invalid refund state transition' using errcode = '23514';
  end if;
  if old.provider_refund_id is not null
     and new.provider_refund_id is distinct from old.provider_refund_id then
    raise exception 'provider refund identity is immutable once assigned' using errcode = '23514';
  end if;
  new.updated_at := now();
  return new;
end;
$$;

create trigger payment_refunds_guard_update
before update on public.payment_refunds
for each row execute function public.guard_payment_refund_update();

create or replace function public.prevent_payment_refund_journal_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'refund event journals are append-only' using errcode = '55000';
end;
$$;

create trigger payment_refund_provider_events_append_only
before update or delete on public.payment_refund_provider_events
for each row execute function public.prevent_payment_refund_journal_mutation();

create trigger payment_refund_events_append_only
before update or delete on public.payment_refund_events
for each row execute function public.prevent_payment_refund_journal_mutation();

create or replace function public.create_payment_refund_intent(
  p_payment_order_id uuid,
  p_amount_minor bigint,
  p_idempotency_key text,
  p_requested_by uuid,
  p_reason_code text
)
returns table(refund_id uuid, refund_status text, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_order public.payment_orders%rowtype;
  v_existing public.payment_refunds%rowtype;
  v_refund_id uuid;
  v_reserved bigint;
begin
  if p_payment_order_id is null or p_amount_minor is null or p_amount_minor <= 0
     or p_idempotency_key is null or char_length(p_idempotency_key) not between 8 and 200
     or p_requested_by is null
     or p_reason_code is null or p_reason_code !~ '^[a-z0-9_]{1,64}$' then
    raise exception 'invalid refund intent parameters' using errcode = '22023';
  end if;

  select * into v_order from public.payment_orders
   where id = p_payment_order_id for update;
  if not found then
    raise exception 'payment order not found' using errcode = 'P0002';
  end if;

  select * into v_existing from public.payment_refunds
   where payment_order_id = p_payment_order_id
     and idempotency_key = p_idempotency_key;
  if found then
    if v_existing.amount_minor is distinct from p_amount_minor
       or v_existing.requested_by is distinct from p_requested_by
       or v_existing.reason_code is distinct from p_reason_code then
      raise exception 'refund idempotency key reused with different parameters'
        using errcode = '23505';
    end if;
    return query select v_existing.id, v_existing.status, true;
    return;
  end if;

  if v_order.status not in ('succeeded','partially_refunded') then
    raise exception 'only settled, not-fully-refunded orders can be refunded'
      using errcode = '55000';
  end if;

  select coalesce(sum(r.amount_minor),0) into v_reserved
    from public.payment_refunds r
   where r.payment_order_id = p_payment_order_id
     and r.status in ('requested','submitted','succeeded');

  if p_amount_minor > v_order.amount_minor - v_reserved then
    raise exception 'refund amount exceeds remaining refundable amount'
      using errcode = '22023';
  end if;

  insert into public.payment_refunds(
    payment_order_id, user_id, provider_code, amount_minor, currency_code,
    idempotency_key, reason_code, requested_by
  ) values (
    v_order.id, v_order.user_id, v_order.provider_code, p_amount_minor,
    v_order.currency_code, p_idempotency_key, p_reason_code, p_requested_by
  ) returning id into v_refund_id;

  insert into public.payment_refund_events(
    refund_id, actor_type, actor_user_id, event_type, previous_status,
    new_status, event_key, reason_code
  ) values (
    v_refund_id, 'admin', p_requested_by, 'refund.requested', null,
    'requested', 'requested:' || p_idempotency_key, p_reason_code
  );

  return query select v_refund_id, 'requested'::text, false;
end;
$$;

create or replace function public.record_verified_payment_refund_provider_event(
  p_provider_code text,
  p_provider_event_id text,
  p_refund_id uuid,
  p_event_type text,
  p_payload_sha256 text,
  p_amount_minor bigint,
  p_currency_code text,
  p_provider_refund_id text
)
returns table(event_id uuid, replayed boolean, resulting_status text)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing_event public.payment_refund_provider_events%rowtype;
  v_refund public.payment_refunds%rowtype;
  v_order public.payment_orders%rowtype;
  v_event_id uuid;
  v_new_status text;
  v_order_status text;
  v_refunded_total bigint;
  v_purchase_type text;
begin
  if p_provider_code is null or p_provider_code !~ '^[a-z][a-z0-9_]{1,39}$'
     or p_provider_event_id is null or char_length(p_provider_event_id) not between 1 and 240
     or p_refund_id is null
     or p_event_type is null or p_event_type not in (
       'refund.pending','refund.succeeded','refund.failed','refund.cancelled'
     )
     or p_payload_sha256 is null or p_payload_sha256 !~ '^[a-f0-9]{64}$'
     or p_amount_minor is null or p_amount_minor <= 0
     or p_currency_code is null or p_currency_code !~ '^[A-Z]{3}$'
     or p_provider_refund_id is null or char_length(p_provider_refund_id) not between 1 and 240 then
    raise exception 'invalid normalized provider refund event' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended(p_provider_code || ':' || p_provider_event_id, 0)
  );

  select * into v_existing_event from public.payment_refund_provider_events
   where provider_code = p_provider_code and provider_event_id = p_provider_event_id;
  if found then
    select * into v_refund from public.payment_refunds where id = v_existing_event.refund_id;
    if v_existing_event.payload_sha256 is distinct from p_payload_sha256
       or v_existing_event.refund_id is distinct from p_refund_id
       or v_existing_event.event_type is distinct from p_event_type
       or v_existing_event.amount_minor is distinct from p_amount_minor
       or v_existing_event.currency_code is distinct from p_currency_code
       or v_existing_event.provider_refund_id is distinct from p_provider_refund_id
       or v_refund.amount_minor is distinct from p_amount_minor
       or v_refund.currency_code is distinct from p_currency_code
       or v_refund.provider_code is distinct from p_provider_code then
      raise exception 'provider refund event replay does not match original normalized payload'
        using errcode = '23505';
    end if;
    return query select v_existing_event.id, true, v_refund.status;
    return;
  end if;

  select * into v_refund from public.payment_refunds where id = p_refund_id;
  if not found then
    raise exception 'refund intent not found' using errcode = 'P0002';
  end if;

  select * into v_order from public.payment_orders
   where id = v_refund.payment_order_id for update;
  select * into v_refund from public.payment_refunds
   where id = p_refund_id for update;

  if v_refund.provider_code is distinct from p_provider_code
     or v_refund.amount_minor is distinct from p_amount_minor
     or v_refund.currency_code is distinct from p_currency_code then
    raise exception 'provider refund does not match immutable refund intent'
      using errcode = '23514';
  end if;
  if v_order.status not in ('succeeded','partially_refunded') then
    raise exception 'payment order is no longer eligible for refund settlement'
      using errcode = '55000';
  end if;
  if v_refund.provider_refund_id is not null
     and v_refund.provider_refund_id is distinct from p_provider_refund_id then
    raise exception 'provider refund identifier mismatch' using errcode = '23514';
  end if;
  if v_refund.status not in ('requested','submitted') then
    raise exception 'refund intent is already terminal' using errcode = '55000';
  end if;

  insert into public.payment_refund_provider_events(
    provider_code, provider_event_id, refund_id, event_type, payload_sha256,
    amount_minor, currency_code, provider_refund_id, signature_verified
  ) values (
    p_provider_code, p_provider_event_id, p_refund_id, p_event_type, p_payload_sha256,
    p_amount_minor, p_currency_code, p_provider_refund_id, true
  ) returning id into v_event_id;

  v_new_status := case
    when p_event_type = 'refund.pending' then 'submitted'
    when p_event_type = 'refund.succeeded' then 'succeeded'
    when p_event_type = 'refund.failed' then 'failed'
    else 'cancelled'
  end;

  if v_refund.status = 'submitted' and v_new_status = 'submitted' then
    return query select v_event_id, false, 'submitted'::text;
    return;
  end if;

  update public.payment_refunds
     set status = v_new_status,
         provider_refund_id = coalesce(provider_refund_id, p_provider_refund_id),
         submitted_at = case when v_new_status = 'submitted' then coalesce(submitted_at, now()) else submitted_at end,
         settled_at = case when v_new_status = 'succeeded' then now() else null end,
         closed_at = case when v_new_status in ('failed','cancelled') then now() else null end
   where id = p_refund_id;

  insert into public.payment_refund_events(
    refund_id, actor_type, event_type, previous_status, new_status,
    event_key, reason_code
  ) values (
    p_refund_id, 'provider', p_event_type, v_refund.status, v_new_status,
    'provider-event:' || md5(p_provider_code || ':' || p_provider_event_id),
    replace(p_event_type, '.', '_')
  );

  if v_new_status = 'succeeded' then
    select coalesce(sum(r.amount_minor),0) into v_refunded_total
      from public.payment_refunds r
     where r.payment_order_id = v_order.id and r.status = 'succeeded';
    if v_refunded_total > v_order.amount_minor then
      raise exception 'settled refunds exceed original payment amount'
        using errcode = '23514';
    end if;

    v_order_status := case
      when v_refunded_total = v_order.amount_minor then 'refunded'
      else 'partially_refunded'
    end;

    update public.payment_orders
       set status = v_order_status,
           closed_at = case when v_order_status = 'refunded' then now() else null end
     where id = v_order.id;

    insert into public.payment_order_events(
      payment_order_id, actor_type, event_type, previous_status,
      new_status, reason_code
    ) values (
      v_order.id, 'provider',
      case when v_order_status = 'refunded' then 'payment.refunded' else 'payment.partially_refunded' end,
      v_order.status, v_order_status, 'provider_refund_succeeded'
    );

    select i.item_type into v_purchase_type
      from public.payment_order_purchase_items i
     where i.payment_order_id = v_order.id and i.user_id = v_order.user_id;
    if v_purchase_type is null then
      raise exception 'refunded payment has no immutable purchase snapshot'
        using errcode = '23514';
    end if;

    insert into public.payment_refund_reconciliations(
      refund_id, payment_order_id, user_id, purchase_type,
      amount_minor, currency_code, status
    ) values (
      p_refund_id, v_order.id, v_order.user_id, v_purchase_type,
      p_amount_minor, p_currency_code, 'pending_review'
    );
  end if;

  return query select v_event_id, false, v_new_status;
end;
$$;

alter table public.payment_refunds enable row level security;
alter table public.payment_refund_provider_events enable row level security;
alter table public.payment_refund_events enable row level security;
alter table public.payment_refund_reconciliations enable row level security;

revoke all on public.payment_refunds, public.payment_refund_provider_events,
  public.payment_refund_events, public.payment_refund_reconciliations
  from public, anon, authenticated, service_role;
grant select on public.payment_refunds, public.payment_refund_provider_events,
  public.payment_refund_events, public.payment_refund_reconciliations
  to service_role;

revoke all on function public.create_payment_refund_intent(uuid,bigint,text,uuid,text)
  from public, anon, authenticated;
revoke all on function public.record_verified_payment_refund_provider_event(
  text,text,uuid,text,text,bigint,text,text
) from public, anon, authenticated;
grant execute on function public.create_payment_refund_intent(uuid,bigint,text,uuid,text)
  to service_role;
grant execute on function public.record_verified_payment_refund_provider_event(
  text,text,uuid,text,text,bigint,text,text
) to service_role;

comment on table public.payment_refunds is
  'Immutable-identity refund intents. Requested/submitted/succeeded amounts reserve the order refundable balance; no provider call is made by this table or its RPC.';
comment on table public.payment_refund_provider_events is
  'Append-only normalized provider refund events. The service-role RPC must only be called after raw webhook signature verification by a provider adapter.';
comment on table public.payment_refund_reconciliations is
  'Queue created after provider-confirmed refunds. Credit or subscription compensation remains pending review; no automatic entitlement mutation occurs.';
comment on function public.create_payment_refund_intent(uuid,bigint,text,uuid,text) is
  'Service-role only. Backend must authorize the actor. Creates a bounded idempotent refund intent; does not call a provider.';
comment on function public.record_verified_payment_refund_provider_event(text,text,uuid,text,text,bigint,text,text) is
  'Service-role only. Call only after provider-specific raw-body signature verification. Records settlement and queues entitlement compensation; does not claw back credits or revoke plans.';
