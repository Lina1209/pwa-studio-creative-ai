-- PWA Studio: entitlement policy gate, bounded expiry sweep and complete wallet aggregates.
-- Policies are inert until an operator explicitly enables a version and sets its amount.

create table if not exists public.credit_entitlement_policies (
  id bigint generated always as identity primary key,
  policy_code text not null,
  policy_version integer not null check (policy_version > 0),
  lot_type text not null check (lot_type in ('free', 'subscription', 'bonus')),
  amount bigint null check (amount is null or amount > 0),
  expires_in_seconds bigint null check (expires_in_seconds is null or expires_in_seconds > 0),
  enabled boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (policy_code, policy_version),
  check (policy_code ~ '^[a-z][a-z0-9_]{2,63}$'),
  check (lot_type not in ('free', 'subscription') or expires_in_seconds is not null)
);

create index if not exists credit_entitlement_policies_enabled_idx
  on public.credit_entitlement_policies(policy_code, policy_version desc)
  where enabled = true;

alter table public.credit_entitlement_policies enable row level security;
revoke all on public.credit_entitlement_policies from public, anon, authenticated;
grant select on public.credit_entitlement_policies to service_role;
grant insert, update, delete on public.credit_entitlement_policies to service_role;
grant usage, select on sequence public.credit_entitlement_policies_id_seq to service_role;

create or replace function public.grant_user_credit_entitlement(
  p_user_id uuid,
  p_policy_code text,
  p_event_key text,
  p_source_reference text,
  p_metadata jsonb default '{}'::jsonb
)
returns table(available_credits bigint, reserved_credits bigint, replayed boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_policy public.credit_entitlement_policies%rowtype;
  v_expires_at timestamptz;
  v_idempotency_key text;
begin
  if p_user_id is null
     or p_policy_code is null or p_policy_code !~ '^[a-z][a-z0-9_]{2,63}$'
     or p_event_key is null or length(p_event_key) not between 8 and 160
     or p_source_reference is null or length(p_source_reference) not between 8 and 240
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 8192 then
    raise exception 'Invalid credit entitlement event' using errcode = '22023';
  end if;

  select * into v_policy
    from public.credit_entitlement_policies
   where policy_code = p_policy_code and enabled = true
   order by policy_version desc limit 1;
  if not found or v_policy.amount is null or v_policy.amount <= 0 then
    raise exception 'Credit entitlement policy is not configured and enabled'
      using errcode = '55000';
  end if;
  if v_policy.expires_in_seconds is not null then
    v_expires_at := now() + make_interval(secs => v_policy.expires_in_seconds::double precision);
  end if;
  v_idempotency_key := 'entitlement:' || v_policy.policy_code || ':' || md5(p_event_key);

  return query
    select g.available_credits, g.reserved_credits, g.replayed
      from public.grant_user_credit_lot(
        p_user_id, v_policy.amount, v_policy.lot_type,
        p_source_reference, v_idempotency_key, v_expires_at,
        p_metadata || jsonb_build_object(
          'policy_code', v_policy.policy_code,
          'policy_version', v_policy.policy_version,
          'event_key_hash', md5(p_event_key)
        )
      ) g;
end;
$$;

revoke all on function public.grant_user_credit_entitlement(uuid,text,text,text,jsonb)
  from public, anon, authenticated;
grant execute on function public.grant_user_credit_entitlement(uuid,text,text,text,jsonb)
  to service_role;

create or replace function public.expire_credit_lots_batch(p_user_limit integer default 100)
returns table(users_processed integer, credits_expired bigint)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_user record;
  v_users integer := 0;
  v_credits bigint := 0;
begin
  if p_user_limit is null or p_user_limit not between 1 and 1000 then
    raise exception 'Expiry batch limit must be between 1 and 1000'
      using errcode = '22023';
  end if;
  for v_user in
    select distinct user_id
      from public.credit_lots
     where available_credits > 0 and expires_at is not null and expires_at <= now()
     order by user_id
     limit p_user_limit
  loop
    v_credits := v_credits + public.expire_credit_lots_for_user(v_user.user_id);
    v_users := v_users + 1;
  end loop;
  return query select v_users, v_credits;
end;
$$;

revoke all on function public.expire_credit_lots_batch(integer) from public, anon, authenticated;
grant execute on function public.expire_credit_lots_batch(integer) to service_role;

-- Keep the full lot totals even though the UI receives only a bounded sample.
create or replace function public.get_credit_wallet_snapshot(
  p_user_id uuid,
  p_history_limit integer default 50
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_holds jsonb;
  v_ledger jsonb;
  v_lots jsonb;
  v_allocations jsonb;
  v_spendable bigint;
  v_lot_available_total bigint;
  v_lot_reserved_total bigint;
  v_lot_count bigint;
  v_allocation_count bigint;
begin
  if p_user_id is null or p_history_limit is null
     or p_history_limit not between 1 and 100 then
    raise exception 'Invalid credit wallet snapshot request'
      using errcode = '22023';
  end if;
  select * into v_wallet from public.credit_wallets where user_id = p_user_id;

  select coalesce(sum(case when expires_at is null or expires_at > now()
                           then available_credits else 0 end), 0),
         coalesce(sum(reserved_credits), 0),
         count(*)
    into v_spendable, v_lot_reserved_total, v_lot_count
    from public.credit_lots where user_id = p_user_id;
  select coalesce(sum(available_credits), 0)
    into v_lot_available_total
    from public.credit_lots where user_id = p_user_id
      and (expires_at is null or expires_at > now());

  select coalesce(jsonb_agg(to_jsonb(h) order by h.created_at desc), '[]'::jsonb)
    into v_holds
    from (
      select id, job_id, amount, status, created_at
        from public.credit_holds where user_id = p_user_id and status = 'held'
       order by created_at desc limit 20
    ) h;

  select coalesce(jsonb_agg(to_jsonb(l) order by l.created_at desc, l.id desc), '[]'::jsonb)
    into v_ledger
    from (
      select id, operation_type, operation_key,
             delta_available, delta_reserved,
             balance_available_after, balance_reserved_after, created_at
        from public.credit_ledger where user_id = p_user_id
       order by created_at desc, id desc limit p_history_limit
    ) l;

  select coalesce(jsonb_agg(to_jsonb(lot) order by lot.expires_at asc nulls last,
                            lot.created_at, lot.id), '[]'::jsonb)
    into v_lots
    from (
      select id, lot_type, granted_credits,
             case when expires_at is not null and expires_at <= now()
                  then 0 else available_credits end as available_credits,
             reserved_credits, expires_at, created_at
        from public.credit_lots where user_id = p_user_id
       order by expires_at asc nulls last, created_at, id limit 100
    ) lot;

  select count(*) into v_allocation_count
    from public.credit_hold_allocations where user_id = p_user_id and status = 'held';
  select coalesce(jsonb_agg(to_jsonb(a) order by a.created_at, a.id), '[]'::jsonb)
    into v_allocations
    from (
      select id, hold_id, lot_id, amount, status, created_at
        from public.credit_hold_allocations
       where user_id = p_user_id and status = 'held'
       order by created_at, id limit 100
    ) a;

  return jsonb_build_object(
    'user_id', p_user_id,
    'currency_unit', 'credit',
    'available_credits', v_spendable,
    'reserved_credits', coalesce(v_wallet.reserved_credits, 0),
    'lot_available_total', v_lot_available_total,
    'lot_reserved_total', v_lot_reserved_total,
    'lot_count', v_lot_count,
    'lots_truncated', v_lot_count > 100,
    'allocation_count', v_allocation_count,
    'allocations_truncated', v_allocation_count > 100,
    'holds', v_holds, 'ledger', v_ledger,
    'lots', v_lots, 'allocations', v_allocations
  );
end;
$$;

revoke all on function public.get_credit_wallet_snapshot(uuid, integer)
  from public, anon, authenticated;
grant execute on function public.get_credit_wallet_snapshot(uuid, integer) to service_role;

comment on table public.credit_entitlement_policies is
  'Versioned server-only grant policies. New rows are disabled and have no amount until explicitly configured.';
comment on function public.grant_user_credit_entitlement(uuid,text,text,text,jsonb) is
  'Applies the latest enabled, fully configured entitlement policy using an event-derived idempotency key; service role only.';
comment on function public.expire_credit_lots_batch(integer) is
  'Bounded service-only expiry sweep. No scheduler is installed by this migration.';
