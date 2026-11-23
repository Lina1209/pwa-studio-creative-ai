-- Durable, idempotent fulfillment handoff for verified successful payments.
-- This creates an inert outbox only. It does not grant credits or activate plans.
create table public.payment_fulfillment_outbox (
  id uuid primary key default gen_random_uuid(),
  payment_order_id uuid not null unique
    references public.payment_orders(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  provider_code text not null check (provider_code ~ '^[a-z][a-z0-9_]{1,39}$'),
  amount_minor bigint not null check (amount_minor > 0),
  currency_code text not null check (currency_code ~ '^[A-Z]{3}$'),
  status text not null default 'queued' check (status in ('queued','processing','completed','failed','manual_review')),
  created_at timestamptz not null default now()
);
create index payment_fulfillment_outbox_queue_idx
  on public.payment_fulfillment_outbox(status, created_at, id);

alter table public.payment_fulfillment_outbox enable row level security;
revoke all on public.payment_fulfillment_outbox from public, anon, authenticated, service_role;
grant select, insert on public.payment_fulfillment_outbox to service_role;

create or replace function public.prevent_payment_fulfillment_outbox_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'payment fulfillment handoff records are immutable'
    using errcode = '55000';
end;
$$;
create trigger payment_fulfillment_outbox_immutable
before update or delete on public.payment_fulfillment_outbox
for each row execute function public.prevent_payment_fulfillment_outbox_mutation();

alter function public.record_verified_payment_provider_event(text,text,uuid,text,text,bigint,text,text)
  rename to record_verified_payment_provider_event_base;

create or replace function public.record_verified_payment_provider_event(
  p_provider_code text,
  p_provider_event_id text,
  p_payment_order_id uuid,
  p_event_type text,
  p_payload_sha256 text,
  p_amount_minor bigint,
  p_currency_code text,
  p_provider_payment_id text
)
returns table(event_id uuid, replayed boolean, resulting_status text)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_result record;
  v_order public.payment_orders%rowtype;
begin
  select * into v_result
    from public.record_verified_payment_provider_event_base(
      p_provider_code, p_provider_event_id, p_payment_order_id,
      p_event_type, p_payload_sha256, p_amount_minor,
      p_currency_code, p_provider_payment_id
    );

  if v_result.resulting_status = 'succeeded' then
    select * into v_order from public.payment_orders
     where id = p_payment_order_id;
    if not found or v_order.status <> 'succeeded'
       or v_order.provider_code is distinct from p_provider_code
       or v_order.amount_minor is distinct from p_amount_minor
       or v_order.currency_code is distinct from p_currency_code then
      raise exception 'settled payment order failed fulfillment reconciliation'
        using errcode = '23514';
    end if;

    insert into public.payment_fulfillment_outbox(
      payment_order_id, user_id, provider_code, amount_minor, currency_code
    ) values (
      v_order.id, v_order.user_id, v_order.provider_code,
      v_order.amount_minor, v_order.currency_code
    ) on conflict (payment_order_id) do nothing;

    if not exists (
      select 1 from public.payment_fulfillment_outbox
       where payment_order_id = v_order.id
         and user_id = v_order.user_id
         and provider_code = v_order.provider_code
         and amount_minor = v_order.amount_minor
         and currency_code = v_order.currency_code
    ) then
      raise exception 'payment fulfillment replay does not match original order'
        using errcode = '23514';
    end if;
  end if;

  return query select v_result.event_id, v_result.replayed, v_result.resulting_status;
end;
$$;

revoke all on function public.record_verified_payment_provider_event(text,text,uuid,text,text,bigint,text,text)
  from public, anon, authenticated;
grant execute on function public.record_verified_payment_provider_event(text,text,uuid,text,text,bigint,text,text)
  to service_role;

comment on table public.payment_fulfillment_outbox is
  'Immutable, one-per-order handoff created atomically with verified success-event ingestion. Inert until a separately reviewed fulfillment worker validates purchase intent; does not grant credits or activate subscriptions.';
comment on function public.record_verified_payment_provider_event(text,text,uuid,text,text,bigint,text,text) is
  'Service-role only. Verifies normalized event through the base RPC and atomically creates one immutable fulfillment handoff for succeeded orders. Never grants credits or activates plans.';
