-- PWA Studio: provider-neutral payment order foundation.
-- This migration deliberately does not enable checkout or mint credits.
-- Provider-specific signature verification must happen in the application adapter
-- before an event is inserted with signature_verified = true.

create table public.payment_orders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete restrict,
  provider_code text not null check (provider_code ~ '^[a-z][a-z0-9_]{1,39}$'),
  merchant_reference text not null unique,
  provider_payment_id text,
  idempotency_key uuid not null,
  amount_minor bigint not null check (amount_minor > 0),
  currency_code text not null check (currency_code ~ '^[A-Z]{3}$'),
  status text not null default 'created'
    check (status in ('created', 'pending', 'succeeded', 'failed', 'cancelled', 'partially_refunded', 'refunded')),
  description text not null check (length(description) between 1 and 240),
  metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(metadata) = 'object' and octet_length(metadata::text) <= 4096),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  paid_at timestamptz,
  closed_at timestamptz,
  unique (user_id, idempotency_key),
  unique (provider_code, provider_payment_id),
  constraint payment_order_terminal_shape check (
    (status in ('created', 'pending') and paid_at is null and closed_at is null)
    or (status = 'succeeded' and paid_at is not null and closed_at is null)
    or (status in ('failed', 'cancelled', 'refunded') and closed_at is not null)
    or (status = 'partially_refunded' and paid_at is not null and closed_at is null)
  )
);

create index payment_orders_user_timeline_idx
  on public.payment_orders(user_id, created_at desc, id desc);
create index payment_orders_status_idx
  on public.payment_orders(status, created_at, id);

create table public.payment_provider_events (
  id uuid primary key default gen_random_uuid(),
  provider_code text not null check (provider_code ~ '^[a-z][a-z0-9_]{1,39}$'),
  provider_event_id text not null check (length(provider_event_id) between 1 and 240),
  payment_order_id uuid references public.payment_orders(id) on delete restrict,
  event_type text not null check (length(event_type) between 1 and 120),
  payload_sha256 text not null check (payload_sha256 ~ '^[a-f0-9]{64}$'),
  signature_verified boolean not null check (signature_verified = true),
  processing_status text not null default 'received'
    check (processing_status in ('received', 'processed', 'ignored', 'failed')),
  received_at timestamptz not null default now(),
  processed_at timestamptz,
  processing_error_code text check (
    processing_error_code is null or processing_error_code ~ '^[a-z0-9_]{1,64}$'
  ),
  unique (provider_code, provider_event_id),
  constraint payment_provider_event_processing_shape check (
    (processing_status = 'received' and processed_at is null)
    or (processing_status in ('processed', 'ignored', 'failed') and processed_at is not null)
  )
);

create index payment_provider_events_order_timeline_idx
  on public.payment_provider_events(payment_order_id, received_at, id);
create index payment_provider_events_inbox_idx
  on public.payment_provider_events(processing_status, received_at, id);

create table public.payment_order_events (
  id uuid primary key default gen_random_uuid(),
  payment_order_id uuid not null references public.payment_orders(id) on delete restrict,
  actor_type text not null check (actor_type in ('system', 'provider', 'admin')),
  event_type text not null check (length(event_type) between 1 and 120),
  previous_status text,
  new_status text not null check (new_status in ('created', 'pending', 'succeeded', 'failed', 'cancelled', 'partially_refunded', 'refunded')),
  reason_code text not null check (reason_code ~ '^[a-z0-9_]{1,64}$'),
  occurred_at timestamptz not null default now()
);
create index payment_order_events_timeline_idx
  on public.payment_order_events(payment_order_id, occurred_at, id);

create or replace function public.guard_payment_order_update()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  if new.user_id is distinct from old.user_id
     or new.provider_code is distinct from old.provider_code
     or new.merchant_reference is distinct from old.merchant_reference
     or new.idempotency_key is distinct from old.idempotency_key
     or new.amount_minor is distinct from old.amount_minor
     or new.currency_code is distinct from old.currency_code
     or new.description is distinct from old.description
     or new.created_at is distinct from old.created_at then
    raise exception 'payment order identity and amount are immutable' using errcode = '23514';
  end if;

  if new.status is distinct from old.status and not (
    (old.status = 'created' and new.status in ('pending', 'succeeded', 'cancelled', 'failed'))
    or (old.status = 'pending' and new.status in ('succeeded', 'failed', 'cancelled'))
    or (old.status = 'succeeded' and new.status in ('partially_refunded', 'refunded'))
    or (old.status = 'partially_refunded' and new.status = 'refunded')
  ) then
    raise exception 'invalid payment order state transition' using errcode = '23514';
  end if;

  new.updated_at := now();
  return new;
end;
$$;

create trigger payment_orders_guard_update
before update on public.payment_orders
for each row execute function public.guard_payment_order_update();

create or replace function public.prevent_payment_event_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'payment event journals are append-only' using errcode = '55000';
end;
$$;

create trigger payment_order_events_append_only
before update or delete on public.payment_order_events
for each row execute function public.prevent_payment_event_mutation();

-- The inbox identity and verified payload digest are immutable. Only processing
-- outcome fields may change as a worker handles an already verified event.
create or replace function public.guard_payment_provider_event_update()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  if new.provider_code is distinct from old.provider_code
     or new.provider_event_id is distinct from old.provider_event_id
     or new.payment_order_id is distinct from old.payment_order_id
     or new.event_type is distinct from old.event_type
     or new.payload_sha256 is distinct from old.payload_sha256
     or new.signature_verified is distinct from old.signature_verified
     or new.received_at is distinct from old.received_at then
    raise exception 'verified payment provider event identity is immutable' using errcode = '23514';
  end if;
  if old.processing_status <> 'received' then
    raise exception 'processed payment provider events are immutable' using errcode = '55000';
  end if;
  if new.processing_status = 'received' or new.processed_at is null then
    raise exception 'payment event outcome must be terminal' using errcode = '23514';
  end if;
  return new;
end;
$$;

create trigger payment_provider_events_guard_update
before update on public.payment_provider_events
for each row execute function public.guard_payment_provider_event_update();

alter table public.payment_orders enable row level security;
alter table public.payment_provider_events enable row level security;
alter table public.payment_order_events enable row level security;

revoke all on public.payment_orders, public.payment_provider_events, public.payment_order_events
  from public, anon, authenticated;
grant select, insert, update on public.payment_orders to service_role;
grant select, insert, update on public.payment_provider_events to service_role;
grant select, insert on public.payment_order_events to service_role;
revoke update, delete on public.payment_order_events from service_role;
revoke delete on public.payment_orders, public.payment_provider_events from service_role;

comment on table public.payment_orders is
  'Provider-neutral payment orders. No row in this table alone grants credits or proves settlement.';
comment on table public.payment_provider_events is
  'Webhook inbox: only persist after provider-specific raw-body signature verification; unique provider event id prevents replay.';
comment on table public.payment_order_events is
  'Append-only payment order state transition journal.';
