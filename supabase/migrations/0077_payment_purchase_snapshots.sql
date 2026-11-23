-- PWA Studio: immutable purchase snapshots bound to approved catalog versions.
-- This migration creates no checkout route and does not activate payments.
-- All order creation remains service-role only; prices are read from approved rows.

create table public.approved_credit_pack_versions (
  id uuid primary key default gen_random_uuid(),
  sku_code text not null check (sku_code ~ '^[a-z][a-z0-9_]{2,40}$'),
  sku_version integer not null check (sku_version > 0),
  display_name text not null check (char_length(display_name) between 1 and 80),
  credits bigint not null check (credits > 0 and credits <= 1000000000000),
  price_minor bigint not null check (price_minor > 0),
  currency char(3) not null check (currency ~ '^[A-Z]{3}$'),
  credit_validity_days integer not null default 365
    check (credit_validity_days between 1 and 3650),
  approved_by uuid not null references auth.users(id) on delete restrict,
  approval_reason text not null check (char_length(approval_reason) between 8 and 500),
  approved_at timestamptz not null default now(),
  unique (sku_code, sku_version)
);

create or replace function public.prevent_approved_credit_pack_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'approved credit pack versions are immutable; approve a new version'
    using errcode = '55000';
end;
$$;

create trigger approved_credit_pack_versions_immutable
before update or delete on public.approved_credit_pack_versions
for each row execute function public.prevent_approved_credit_pack_mutation();

alter table public.approved_credit_pack_versions enable row level security;
revoke all on public.approved_credit_pack_versions from public, anon, authenticated;
grant select on public.approved_credit_pack_versions to service_role;

create or replace function public.approve_credit_pack_version(
  p_sku_code text,
  p_sku_version integer,
  p_display_name text,
  p_credits bigint,
  p_price_minor bigint,
  p_currency text,
  p_credit_validity_days integer,
  p_actor_user_id uuid,
  p_approval_reason text
)
returns table(approved_credit_pack_version_id uuid, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $
declare
  v_existing public.approved_credit_pack_versions%rowtype;
  v_id uuid;
begin
  if p_sku_code is null or p_sku_code !~ '^[a-z][a-z0-9_]{2,40}
  payment_order_id uuid primary key
    references public.payment_orders(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  item_type text not null check (item_type in ('credit_pack','subscription')),
  approved_credit_pack_version_id uuid
    references public.approved_credit_pack_versions(id) on delete restrict,
  approved_plan_version_id uuid
    references public.approved_plan_versions(id) on delete restrict,
  sku_code text not null check (sku_code ~ '^[a-z][a-z0-9_]{2,40}$'),
  sku_version integer not null check (sku_version > 0),
  display_name text not null check (char_length(display_name) between 1 and 80),
  amount_minor bigint not null check (amount_minor > 0),
  currency_code char(3) not null check (currency_code ~ '^[A-Z]{3}$'),
  credit_quantity bigint not null check (credit_quantity > 0),
  credit_validity_days integer,
  plan_period_days integer,
  created_at timestamptz not null default now(),
  constraint payment_order_purchase_item_kind check (
    (item_type = 'credit_pack'
      and approved_credit_pack_version_id is not null
      and approved_plan_version_id is null
      and credit_validity_days between 1 and 3650
      and plan_period_days is null)
    or
    (item_type = 'subscription'
      and approved_plan_version_id is not null
      and approved_credit_pack_version_id is null
      and credit_validity_days is null
      and plan_period_days in (7,30))
  )
);

create index payment_order_purchase_items_user_idx
  on public.payment_order_purchase_items(user_id, created_at desc);

create or replace function public.prevent_payment_order_purchase_item_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'payment purchase snapshots are immutable'
    using errcode = '55000';
end;
$$;

create trigger payment_order_purchase_items_immutable
before update or delete on public.payment_order_purchase_items
for each row execute function public.prevent_payment_order_purchase_item_mutation();

alter table public.payment_order_purchase_items enable row level security;
revoke all on public.payment_order_purchase_items from public, anon, authenticated, service_role;
grant select on public.payment_order_purchase_items to service_role;

create or replace function public.create_credit_pack_payment_order(
  p_user_id uuid,
  p_provider_code text,
  p_merchant_reference text,
  p_idempotency_key uuid,
  p_credit_pack_version_id uuid,
  p_metadata jsonb default '{}'::jsonb
)
returns table(payment_order_id uuid, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_pack public.approved_credit_pack_versions%rowtype;
  v_order_id uuid;
  v_replayed boolean;
  v_existing public.payment_order_purchase_items%rowtype;
  v_metadata jsonb;
begin
  if p_user_id is null or p_credit_pack_version_id is null
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 2048 then
    raise exception 'invalid credit pack purchase parameters' using errcode = '22023';
  end if;

  select * into v_pack from public.approved_credit_pack_versions
   where id = p_credit_pack_version_id;
  if not found then
    raise exception 'approved credit pack version not found' using errcode = 'P0002';
  end if;

  v_metadata := p_metadata || jsonb_build_object(
    'purchase_type', 'credit_pack',
    'approved_credit_pack_version_id', v_pack.id,
    'sku_code', v_pack.sku_code,
    'sku_version', v_pack.sku_version
  );
  if octet_length(v_metadata::text) > 4096 then
    raise exception 'purchase metadata is too large' using errcode = '22023';
  end if;

  select o.payment_order_id, o.replayed into v_order_id, v_replayed
    from public.create_payment_order(
      p_user_id, p_provider_code, p_merchant_reference, p_idempotency_key,
      v_pack.price_minor, v_pack.currency, v_pack.display_name, v_metadata
    ) o;

  insert into public.payment_order_purchase_items(
    payment_order_id, user_id, item_type, approved_credit_pack_version_id,
    sku_code, sku_version, display_name, amount_minor, currency_code,
    credit_quantity, credit_validity_days, plan_period_days
  ) values (
    v_order_id, p_user_id, 'credit_pack', v_pack.id,
    v_pack.sku_code, v_pack.sku_version, v_pack.display_name,
    v_pack.price_minor, v_pack.currency, v_pack.credits,
    v_pack.credit_validity_days, null
  ) on conflict (payment_order_id) do nothing;

  select * into v_existing from public.payment_order_purchase_items
   where payment_order_id = v_order_id;
  if not found or v_existing.user_id is distinct from p_user_id
     or v_existing.item_type <> 'credit_pack'
     or v_existing.approved_credit_pack_version_id is distinct from v_pack.id
     or v_existing.sku_code <> v_pack.sku_code
     or v_existing.sku_version <> v_pack.sku_version
     or v_existing.amount_minor <> v_pack.price_minor
     or v_existing.currency_code <> v_pack.currency
     or v_existing.credit_quantity <> v_pack.credits
     or v_existing.credit_validity_days <> v_pack.credit_validity_days then
    raise exception 'payment order purchase snapshot conflicts with approved credit pack'
      using errcode = '23514';
  end if;

  return query select v_order_id, v_replayed;
end;
$$;

create or replace function public.create_subscription_payment_order(
  p_user_id uuid,
  p_provider_code text,
  p_merchant_reference text,
  p_idempotency_key uuid,
  p_approved_plan_version_id uuid,
  p_metadata jsonb default '{}'::jsonb
)
returns table(payment_order_id uuid, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_plan public.approved_plan_versions%rowtype;
  v_order_id uuid;
  v_replayed boolean;
  v_existing public.payment_order_purchase_items%rowtype;
  v_metadata jsonb;
begin
  if p_user_id is null or p_approved_plan_version_id is null
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 2048 then
    raise exception 'invalid subscription purchase parameters' using errcode = '22023';
  end if;

  select * into v_plan from public.approved_plan_versions
   where id = p_approved_plan_version_id;
  if not found then
    raise exception 'approved plan version not found' using errcode = 'P0002';
  end if;
  if v_plan.price_minor is null or v_plan.currency is null then
    raise exception 'approved plan version is not purchasable' using errcode = '55000';
  end if;

  v_metadata := p_metadata || jsonb_build_object(
    'purchase_type', 'subscription',
    'approved_plan_version_id', v_plan.id,
    'plan_code', v_plan.plan_code,
    'plan_version', v_plan.plan_version
  );
  if octet_length(v_metadata::text) > 4096 then
    raise exception 'purchase metadata is too large' using errcode = '22023';
  end if;

  select o.payment_order_id, o.replayed into v_order_id, v_replayed
    from public.create_payment_order(
      p_user_id, p_provider_code, p_merchant_reference, p_idempotency_key,
      v_plan.price_minor, v_plan.currency, v_plan.display_name, v_metadata
    ) o;

  insert into public.payment_order_purchase_items(
    payment_order_id, user_id, item_type, approved_plan_version_id,
    sku_code, sku_version, display_name, amount_minor, currency_code,
    credit_quantity, credit_validity_days, plan_period_days
  ) values (
    v_order_id, p_user_id, 'subscription', v_plan.id,
    v_plan.plan_code, v_plan.plan_version, v_plan.display_name,
    v_plan.price_minor, v_plan.currency, v_plan.credits_per_period,
    null, v_plan.period_days
  ) on conflict (payment_order_id) do nothing;

  select * into v_existing from public.payment_order_purchase_items
   where payment_order_id = v_order_id;
  if not found or v_existing.user_id is distinct from p_user_id
     or v_existing.item_type <> 'subscription'
     or v_existing.approved_plan_version_id is distinct from v_plan.id
     or v_existing.sku_code <> v_plan.plan_code
     or v_existing.sku_version <> v_plan.plan_version
     or v_existing.amount_minor <> v_plan.price_minor
     or v_existing.currency_code <> v_plan.currency
     or v_existing.credit_quantity <> v_plan.credits_per_period
     or v_existing.plan_period_days <> v_plan.period_days then
    raise exception 'payment order purchase snapshot conflicts with approved plan'
      using errcode = '23514';
  end if;

  return query select v_order_id, v_replayed;
end;
$$;

revoke all on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb)
  from public, anon, authenticated;
revoke all on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb)
  from public, anon, authenticated;
grant execute on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb)
  to service_role;
grant execute on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb)
  to service_role;

comment on table public.approved_credit_pack_versions is
  'Immutable approved credit pack catalog. Service-role insertion is intended only behind backend admin authorization.';
comment on table public.payment_order_purchase_items is
  'One immutable approved-catalog purchase snapshot per payment order; order amount and currency are derived from this row.';
comment on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb) is
  'Service-role only. Creates an order priced from an approved immutable credit pack and binds its exact purchase snapshot atomically.';
comment on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb) is
  'Service-role only. Creates an order priced from an approved immutable plan version and binds its exact purchase snapshot atomically.';

     or p_sku_version is null or p_sku_version <= 0
     or p_display_name is null or char_length(p_display_name) not between 1 and 80
     or p_credits is null or p_credits <= 0 or p_credits > 1000000000000
     or p_price_minor is null or p_price_minor <= 0
     or p_currency is null or p_currency !~ '^[A-Z]{3}
  payment_order_id uuid primary key
    references public.payment_orders(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  item_type text not null check (item_type in ('credit_pack','subscription')),
  approved_credit_pack_version_id uuid
    references public.approved_credit_pack_versions(id) on delete restrict,
  approved_plan_version_id uuid
    references public.approved_plan_versions(id) on delete restrict,
  sku_code text not null check (sku_code ~ '^[a-z][a-z0-9_]{2,40}$'),
  sku_version integer not null check (sku_version > 0),
  display_name text not null check (char_length(display_name) between 1 and 80),
  amount_minor bigint not null check (amount_minor > 0),
  currency_code char(3) not null check (currency_code ~ '^[A-Z]{3}$'),
  credit_quantity bigint not null check (credit_quantity > 0),
  credit_validity_days integer,
  plan_period_days integer,
  created_at timestamptz not null default now(),
  constraint payment_order_purchase_item_kind check (
    (item_type = 'credit_pack'
      and approved_credit_pack_version_id is not null
      and approved_plan_version_id is null
      and credit_validity_days between 1 and 3650
      and plan_period_days is null)
    or
    (item_type = 'subscription'
      and approved_plan_version_id is not null
      and approved_credit_pack_version_id is null
      and credit_validity_days is null
      and plan_period_days in (7,30))
  )
);

create index payment_order_purchase_items_user_idx
  on public.payment_order_purchase_items(user_id, created_at desc);

create or replace function public.prevent_payment_order_purchase_item_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'payment purchase snapshots are immutable'
    using errcode = '55000';
end;
$$;

create trigger payment_order_purchase_items_immutable
before update or delete on public.payment_order_purchase_items
for each row execute function public.prevent_payment_order_purchase_item_mutation();

alter table public.payment_order_purchase_items enable row level security;
revoke all on public.payment_order_purchase_items from public, anon, authenticated, service_role;
grant select on public.payment_order_purchase_items to service_role;

create or replace function public.create_credit_pack_payment_order(
  p_user_id uuid,
  p_provider_code text,
  p_merchant_reference text,
  p_idempotency_key uuid,
  p_credit_pack_version_id uuid,
  p_metadata jsonb default '{}'::jsonb
)
returns table(payment_order_id uuid, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_pack public.approved_credit_pack_versions%rowtype;
  v_order_id uuid;
  v_replayed boolean;
  v_existing public.payment_order_purchase_items%rowtype;
  v_metadata jsonb;
begin
  if p_user_id is null or p_credit_pack_version_id is null
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 2048 then
    raise exception 'invalid credit pack purchase parameters' using errcode = '22023';
  end if;

  select * into v_pack from public.approved_credit_pack_versions
   where id = p_credit_pack_version_id;
  if not found then
    raise exception 'approved credit pack version not found' using errcode = 'P0002';
  end if;

  v_metadata := p_metadata || jsonb_build_object(
    'purchase_type', 'credit_pack',
    'approved_credit_pack_version_id', v_pack.id,
    'sku_code', v_pack.sku_code,
    'sku_version', v_pack.sku_version
  );
  if octet_length(v_metadata::text) > 4096 then
    raise exception 'purchase metadata is too large' using errcode = '22023';
  end if;

  select o.payment_order_id, o.replayed into v_order_id, v_replayed
    from public.create_payment_order(
      p_user_id, p_provider_code, p_merchant_reference, p_idempotency_key,
      v_pack.price_minor, v_pack.currency, v_pack.display_name, v_metadata
    ) o;

  insert into public.payment_order_purchase_items(
    payment_order_id, user_id, item_type, approved_credit_pack_version_id,
    sku_code, sku_version, display_name, amount_minor, currency_code,
    credit_quantity, credit_validity_days, plan_period_days
  ) values (
    v_order_id, p_user_id, 'credit_pack', v_pack.id,
    v_pack.sku_code, v_pack.sku_version, v_pack.display_name,
    v_pack.price_minor, v_pack.currency, v_pack.credits,
    v_pack.credit_validity_days, null
  ) on conflict (payment_order_id) do nothing;

  select * into v_existing from public.payment_order_purchase_items
   where payment_order_id = v_order_id;
  if not found or v_existing.user_id is distinct from p_user_id
     or v_existing.item_type <> 'credit_pack'
     or v_existing.approved_credit_pack_version_id is distinct from v_pack.id
     or v_existing.sku_code <> v_pack.sku_code
     or v_existing.sku_version <> v_pack.sku_version
     or v_existing.amount_minor <> v_pack.price_minor
     or v_existing.currency_code <> v_pack.currency
     or v_existing.credit_quantity <> v_pack.credits
     or v_existing.credit_validity_days <> v_pack.credit_validity_days then
    raise exception 'payment order purchase snapshot conflicts with approved credit pack'
      using errcode = '23514';
  end if;

  return query select v_order_id, v_replayed;
end;
$$;

create or replace function public.create_subscription_payment_order(
  p_user_id uuid,
  p_provider_code text,
  p_merchant_reference text,
  p_idempotency_key uuid,
  p_approved_plan_version_id uuid,
  p_metadata jsonb default '{}'::jsonb
)
returns table(payment_order_id uuid, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_plan public.approved_plan_versions%rowtype;
  v_order_id uuid;
  v_replayed boolean;
  v_existing public.payment_order_purchase_items%rowtype;
  v_metadata jsonb;
begin
  if p_user_id is null or p_approved_plan_version_id is null
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 2048 then
    raise exception 'invalid subscription purchase parameters' using errcode = '22023';
  end if;

  select * into v_plan from public.approved_plan_versions
   where id = p_approved_plan_version_id;
  if not found then
    raise exception 'approved plan version not found' using errcode = 'P0002';
  end if;
  if v_plan.price_minor is null or v_plan.currency is null then
    raise exception 'approved plan version is not purchasable' using errcode = '55000';
  end if;

  v_metadata := p_metadata || jsonb_build_object(
    'purchase_type', 'subscription',
    'approved_plan_version_id', v_plan.id,
    'plan_code', v_plan.plan_code,
    'plan_version', v_plan.plan_version
  );
  if octet_length(v_metadata::text) > 4096 then
    raise exception 'purchase metadata is too large' using errcode = '22023';
  end if;

  select o.payment_order_id, o.replayed into v_order_id, v_replayed
    from public.create_payment_order(
      p_user_id, p_provider_code, p_merchant_reference, p_idempotency_key,
      v_plan.price_minor, v_plan.currency, v_plan.display_name, v_metadata
    ) o;

  insert into public.payment_order_purchase_items(
    payment_order_id, user_id, item_type, approved_plan_version_id,
    sku_code, sku_version, display_name, amount_minor, currency_code,
    credit_quantity, credit_validity_days, plan_period_days
  ) values (
    v_order_id, p_user_id, 'subscription', v_plan.id,
    v_plan.plan_code, v_plan.plan_version, v_plan.display_name,
    v_plan.price_minor, v_plan.currency, v_plan.credits_per_period,
    null, v_plan.period_days
  ) on conflict (payment_order_id) do nothing;

  select * into v_existing from public.payment_order_purchase_items
   where payment_order_id = v_order_id;
  if not found or v_existing.user_id is distinct from p_user_id
     or v_existing.item_type <> 'subscription'
     or v_existing.approved_plan_version_id is distinct from v_plan.id
     or v_existing.sku_code <> v_plan.plan_code
     or v_existing.sku_version <> v_plan.plan_version
     or v_existing.amount_minor <> v_plan.price_minor
     or v_existing.currency_code <> v_plan.currency
     or v_existing.credit_quantity <> v_plan.credits_per_period
     or v_existing.plan_period_days <> v_plan.period_days then
    raise exception 'payment order purchase snapshot conflicts with approved plan'
      using errcode = '23514';
  end if;

  return query select v_order_id, v_replayed;
end;
$$;

revoke all on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb)
  from public, anon, authenticated;
revoke all on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb)
  from public, anon, authenticated;
grant execute on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb)
  to service_role;
grant execute on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb)
  to service_role;

comment on table public.approved_credit_pack_versions is
  'Immutable approved credit pack catalog. Service-role insertion is intended only behind backend admin authorization.';
comment on table public.payment_order_purchase_items is
  'One immutable approved-catalog purchase snapshot per payment order; order amount and currency are derived from this row.';
comment on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb) is
  'Service-role only. Creates an order priced from an approved immutable credit pack and binds its exact purchase snapshot atomically.';
comment on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb) is
  'Service-role only. Creates an order priced from an approved immutable plan version and binds its exact purchase snapshot atomically.';

     or p_credit_validity_days is null or p_credit_validity_days not between 1 and 3650
     or p_actor_user_id is null
     or p_approval_reason is null or char_length(p_approval_reason) not between 8 and 500 then
    raise exception 'invalid approved credit pack parameters' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended('credit-pack:' || p_sku_code || ':' || p_sku_version::text, 0)
  );

  select * into v_existing from public.approved_credit_pack_versions
   where sku_code = p_sku_code and sku_version = p_sku_version;
  if found then
    if v_existing.display_name is distinct from p_display_name
       or v_existing.credits is distinct from p_credits
       or v_existing.price_minor is distinct from p_price_minor
       or v_existing.currency is distinct from p_currency
       or v_existing.credit_validity_days is distinct from p_credit_validity_days
       or v_existing.approved_by is distinct from p_actor_user_id
       or v_existing.approval_reason is distinct from p_approval_reason then
      raise exception 'credit pack version already exists with different approval facts'
        using errcode = '23505';
    end if;
    return query select v_existing.id, true;
    return;
  end if;

  insert into public.approved_credit_pack_versions(
    sku_code, sku_version, display_name, credits, price_minor,
    currency, credit_validity_days, approved_by, approval_reason
  ) values (
    p_sku_code, p_sku_version, p_display_name, p_credits, p_price_minor,
    p_currency, p_credit_validity_days, p_actor_user_id, p_approval_reason
  ) returning id into v_id;

  perform public.record_admin_audit_event(
    p_actor_user_id,
    'admin.tariff.change.approved',
    'approved',
    'credit_pack',
    v_id,
    null,
    p_approval_reason
  );

  return query select v_id, false;
end;
$;

revoke all on function public.approve_credit_pack_version(
  text,integer,text,bigint,bigint,text,integer,uuid,text
) from public, anon, authenticated;
grant execute on function public.approve_credit_pack_version(
  text,integer,text,bigint,bigint,text,integer,uuid,text
) to service_role;

create table public.payment_order_purchase_items (
  payment_order_id uuid primary key
    references public.payment_orders(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete restrict,
  item_type text not null check (item_type in ('credit_pack','subscription')),
  approved_credit_pack_version_id uuid
    references public.approved_credit_pack_versions(id) on delete restrict,
  approved_plan_version_id uuid
    references public.approved_plan_versions(id) on delete restrict,
  sku_code text not null check (sku_code ~ '^[a-z][a-z0-9_]{2,40}$'),
  sku_version integer not null check (sku_version > 0),
  display_name text not null check (char_length(display_name) between 1 and 80),
  amount_minor bigint not null check (amount_minor > 0),
  currency_code char(3) not null check (currency_code ~ '^[A-Z]{3}$'),
  credit_quantity bigint not null check (credit_quantity > 0),
  credit_validity_days integer,
  plan_period_days integer,
  created_at timestamptz not null default now(),
  constraint payment_order_purchase_item_kind check (
    (item_type = 'credit_pack'
      and approved_credit_pack_version_id is not null
      and approved_plan_version_id is null
      and credit_validity_days between 1 and 3650
      and plan_period_days is null)
    or
    (item_type = 'subscription'
      and approved_plan_version_id is not null
      and approved_credit_pack_version_id is null
      and credit_validity_days is null
      and plan_period_days in (7,30))
  )
);

create index payment_order_purchase_items_user_idx
  on public.payment_order_purchase_items(user_id, created_at desc);

create or replace function public.prevent_payment_order_purchase_item_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'payment purchase snapshots are immutable'
    using errcode = '55000';
end;
$$;

create trigger payment_order_purchase_items_immutable
before update or delete on public.payment_order_purchase_items
for each row execute function public.prevent_payment_order_purchase_item_mutation();

alter table public.payment_order_purchase_items enable row level security;
revoke all on public.payment_order_purchase_items from public, anon, authenticated, service_role;
grant select on public.payment_order_purchase_items to service_role;

create or replace function public.create_credit_pack_payment_order(
  p_user_id uuid,
  p_provider_code text,
  p_merchant_reference text,
  p_idempotency_key uuid,
  p_credit_pack_version_id uuid,
  p_metadata jsonb default '{}'::jsonb
)
returns table(payment_order_id uuid, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_pack public.approved_credit_pack_versions%rowtype;
  v_order_id uuid;
  v_replayed boolean;
  v_existing public.payment_order_purchase_items%rowtype;
  v_metadata jsonb;
begin
  if p_user_id is null or p_credit_pack_version_id is null
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 2048 then
    raise exception 'invalid credit pack purchase parameters' using errcode = '22023';
  end if;

  select * into v_pack from public.approved_credit_pack_versions
   where id = p_credit_pack_version_id;
  if not found then
    raise exception 'approved credit pack version not found' using errcode = 'P0002';
  end if;

  v_metadata := p_metadata || jsonb_build_object(
    'purchase_type', 'credit_pack',
    'approved_credit_pack_version_id', v_pack.id,
    'sku_code', v_pack.sku_code,
    'sku_version', v_pack.sku_version
  );
  if octet_length(v_metadata::text) > 4096 then
    raise exception 'purchase metadata is too large' using errcode = '22023';
  end if;

  select o.payment_order_id, o.replayed into v_order_id, v_replayed
    from public.create_payment_order(
      p_user_id, p_provider_code, p_merchant_reference, p_idempotency_key,
      v_pack.price_minor, v_pack.currency, v_pack.display_name, v_metadata
    ) o;

  insert into public.payment_order_purchase_items(
    payment_order_id, user_id, item_type, approved_credit_pack_version_id,
    sku_code, sku_version, display_name, amount_minor, currency_code,
    credit_quantity, credit_validity_days, plan_period_days
  ) values (
    v_order_id, p_user_id, 'credit_pack', v_pack.id,
    v_pack.sku_code, v_pack.sku_version, v_pack.display_name,
    v_pack.price_minor, v_pack.currency, v_pack.credits,
    v_pack.credit_validity_days, null
  ) on conflict (payment_order_id) do nothing;

  select * into v_existing from public.payment_order_purchase_items
   where payment_order_id = v_order_id;
  if not found or v_existing.user_id is distinct from p_user_id
     or v_existing.item_type <> 'credit_pack'
     or v_existing.approved_credit_pack_version_id is distinct from v_pack.id
     or v_existing.sku_code <> v_pack.sku_code
     or v_existing.sku_version <> v_pack.sku_version
     or v_existing.amount_minor <> v_pack.price_minor
     or v_existing.currency_code <> v_pack.currency
     or v_existing.credit_quantity <> v_pack.credits
     or v_existing.credit_validity_days <> v_pack.credit_validity_days then
    raise exception 'payment order purchase snapshot conflicts with approved credit pack'
      using errcode = '23514';
  end if;

  return query select v_order_id, v_replayed;
end;
$$;

create or replace function public.create_subscription_payment_order(
  p_user_id uuid,
  p_provider_code text,
  p_merchant_reference text,
  p_idempotency_key uuid,
  p_approved_plan_version_id uuid,
  p_metadata jsonb default '{}'::jsonb
)
returns table(payment_order_id uuid, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_plan public.approved_plan_versions%rowtype;
  v_order_id uuid;
  v_replayed boolean;
  v_existing public.payment_order_purchase_items%rowtype;
  v_metadata jsonb;
begin
  if p_user_id is null or p_approved_plan_version_id is null
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 2048 then
    raise exception 'invalid subscription purchase parameters' using errcode = '22023';
  end if;

  select * into v_plan from public.approved_plan_versions
   where id = p_approved_plan_version_id;
  if not found then
    raise exception 'approved plan version not found' using errcode = 'P0002';
  end if;
  if v_plan.price_minor is null or v_plan.currency is null then
    raise exception 'approved plan version is not purchasable' using errcode = '55000';
  end if;

  v_metadata := p_metadata || jsonb_build_object(
    'purchase_type', 'subscription',
    'approved_plan_version_id', v_plan.id,
    'plan_code', v_plan.plan_code,
    'plan_version', v_plan.plan_version
  );
  if octet_length(v_metadata::text) > 4096 then
    raise exception 'purchase metadata is too large' using errcode = '22023';
  end if;

  select o.payment_order_id, o.replayed into v_order_id, v_replayed
    from public.create_payment_order(
      p_user_id, p_provider_code, p_merchant_reference, p_idempotency_key,
      v_plan.price_minor, v_plan.currency, v_plan.display_name, v_metadata
    ) o;

  insert into public.payment_order_purchase_items(
    payment_order_id, user_id, item_type, approved_plan_version_id,
    sku_code, sku_version, display_name, amount_minor, currency_code,
    credit_quantity, credit_validity_days, plan_period_days
  ) values (
    v_order_id, p_user_id, 'subscription', v_plan.id,
    v_plan.plan_code, v_plan.plan_version, v_plan.display_name,
    v_plan.price_minor, v_plan.currency, v_plan.credits_per_period,
    null, v_plan.period_days
  ) on conflict (payment_order_id) do nothing;

  select * into v_existing from public.payment_order_purchase_items
   where payment_order_id = v_order_id;
  if not found or v_existing.user_id is distinct from p_user_id
     or v_existing.item_type <> 'subscription'
     or v_existing.approved_plan_version_id is distinct from v_plan.id
     or v_existing.sku_code <> v_plan.plan_code
     or v_existing.sku_version <> v_plan.plan_version
     or v_existing.amount_minor <> v_plan.price_minor
     or v_existing.currency_code <> v_plan.currency
     or v_existing.credit_quantity <> v_plan.credits_per_period
     or v_existing.plan_period_days <> v_plan.period_days then
    raise exception 'payment order purchase snapshot conflicts with approved plan'
      using errcode = '23514';
  end if;

  return query select v_order_id, v_replayed;
end;
$$;

revoke all on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb)
  from public, anon, authenticated;
revoke all on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb)
  from public, anon, authenticated;
grant execute on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb)
  to service_role;
grant execute on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb)
  to service_role;

comment on table public.approved_credit_pack_versions is
  'Immutable approved credit pack catalog. Service-role insertion is intended only behind backend admin authorization.';
comment on table public.payment_order_purchase_items is
  'One immutable approved-catalog purchase snapshot per payment order; order amount and currency are derived from this row.';
comment on function public.create_credit_pack_payment_order(uuid,text,text,uuid,uuid,jsonb) is
  'Service-role only. Creates an order priced from an approved immutable credit pack and binds its exact purchase snapshot atomically.';
comment on function public.create_subscription_payment_order(uuid,text,text,uuid,uuid,jsonb) is
  'Service-role only. Creates an order priced from an approved immutable plan version and binds its exact purchase snapshot atomically.';

comment on function public.approve_credit_pack_version(
  text,integer,text,bigint,bigint,text,integer,uuid,text
) is
  'Service-role only. Backend must verify administrator authorization before creating an immutable credit pack version; writes the admin audit event in the same transaction.';
