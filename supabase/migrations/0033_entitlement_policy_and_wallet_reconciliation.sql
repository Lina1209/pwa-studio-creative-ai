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
-- Policy changes are deployment/admin operations, not runtime service-role writes.

create table if not exists public.credit_entitlement_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  policy_code text not null,
  event_fingerprint text not null,
  policy_version integer not null,
  lot_type text not null check (lot_type in ('free', 'subscription', 'bonus')),
  amount bigint not null check (amount > 0),
  source_reference text not null,
  expires_at timestamptz,
  idempotency_key text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (user_id, policy_code, event_fingerprint),
  unique (user_id, idempotency_key)
);
alter table public.credit_entitlement_events enable row level security;
revoke all on public.credit_entitlement_events from public, anon, authenticated;
-- Event rows are written only inside the SECURITY DEFINER grant function.

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
  v_event public.credit_entitlement_events%rowtype;
  v_expires_at timestamptz;
  v_idempotency_key text;
  v_fingerprint text;
  v_metadata jsonb;
begin
  if p_user_id is null
     or p_policy_code is null or p_policy_code !~ '^[a-z][a-z0-9_]{2,63}$'
     or p_event_key is null or length(p_event_key) not between 8 and 160
     or p_source_reference is null or length(p_source_reference) not between 8 and 240
     or p_metadata is null or jsonb_typeof(p_metadata) <> 'object'
     or octet_length(p_metadata::text) > 8192 then
    raise exception 'Invalid credit entitlement event' using errcode = '22023';
  end if;

  v_fingerprint := md5(p_event_key);
  v_idempotency_key := 'entitlement:' || p_policy_code || ':' || v_fingerprint;
  select * into v_event
    from public.credit_entitlement_events
   where user_id = p_user_id and policy_code = p_policy_code
     and event_fingerprint = v_fingerprint
   for update;

  if not found then
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
    v_metadata := p_metadata || jsonb_build_object(
      'policy_code', v_policy.policy_code,
      'policy_version', v_policy.policy_version,
      'event_key_hash', v_fingerprint
    );
    insert into public.credit_entitlement_events(
      user_id, policy_code, event_fingerprint, policy_version,
      lot_type, amount, source_reference, expires_at,
      idempotency_key, metadata
    ) values (
      p_user_id, v_policy.policy_code, v_fingerprint, v_policy.policy_version,
      v_policy.lot_type, v_policy.amount, p_source_reference, v_expires_at,
      v_idempotency_key, v_metadata
    ) on conflict (user_id, policy_code, event_fingerprint) do nothing;

    select * into v_event
      from public.credit_entitlement_events
     where user_id = p_user_id and policy_code = p_policy_code
       and event_fingerprint = v_fingerprint
     for update;
  end if;

  if v_event.source_reference <> p_source_reference or v_event.metadata <>
     (p_metadata || jsonb_build_object(
       'policy_code', v_event.policy_code,
       'policy_version', v_event.policy_version,
       'event_key_hash', v_fingerprint
     )) then
    raise exception 'Credit entitlement event replay parameters do not match'
      using errcode = '22023';
  end if;

  return query
    select g.available_credits, g.reserved_credits, g.replayed
      from public.grant_user_credit_lot(
        p_user_id, v_event.amount, v_event.lot_type,
        v_event.source_reference, v_event.idempotency_key,
        v_event.expires_at, v_event.metadata
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

comment on table public.credit_entitlement_events is
  'Immutable event-to-policy snapshot used to make entitlement expiry and idempotency stable across retries and policy revisions.';
comment on table public.credit_entitlement_policies is
  'Versioned server-only grant policies. New rows are disabled and have no amount until explicitly configured.';
comment on function public.grant_user_credit_entitlement(uuid,text,text,text,jsonb) is
  'Applies the latest enabled, fully configured entitlement policy using an event-derived idempotency key; service role only.';
comment on function public.expire_credit_lots_batch(integer) is
  'Bounded service-only expiry sweep. No scheduler is installed by this migration.';


-- Read-only financial reconciliation. It never repairs or mutates balances.
create or replace function public.audit_credit_wallet_reconciliation(
  p_user_id uuid default null,
  p_user_limit integer default 500
)
returns table(
  user_id uuid,
  wallet_available bigint,
  lot_available bigint,
  wallet_reserved bigint,
  lot_reserved bigint,
  held_holds bigint,
  held_allocations bigint,
  latest_ledger_available bigint,
  latest_ledger_reserved bigint,
  wallet_lots_match boolean,
  holds_match boolean,
  allocations_match boolean,
  latest_ledger_matches boolean,
  healthy boolean
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $reconcile$
#variable_conflict use_column
begin
  if p_user_limit is null or p_user_limit not between 1 and 5000 then
    raise exception 'Reconciliation limit must be between 1 and 5000'
      using errcode = '22023';
  end if;

  return query
  with target_users as (
    select w.user_id from public.credit_wallets w
     where p_user_id is null or w.user_id = p_user_id
    union
    select l.user_id from public.credit_lots l
     where p_user_id is null or l.user_id = p_user_id
    union
    select h.user_id from public.credit_holds h
     where p_user_id is null or h.user_id = p_user_id
    union
    -- Include ledger-only identities so a missing wallet projection is visible.
    select e.user_id from public.credit_ledger e
     where p_user_id is null or e.user_id = p_user_id
  ),
  bounded_users as (
    select t.user_id from target_users t order by t.user_id limit p_user_limit
  ),
  wallets as (
    select w.user_id, w.available_credits, w.reserved_credits
      from public.credit_wallets w join bounded_users b using (user_id)
  ),
  lots as (
    select l.user_id,
           coalesce(sum(l.available_credits), 0)::bigint as available,
           coalesce(sum(l.reserved_credits), 0)::bigint as reserved
      from public.credit_lots l join bounded_users b using (user_id)
     group by l.user_id
  ),
  holds as (
    select h.user_id,
           coalesce(sum(h.amount) filter (where h.status = 'held'), 0)::bigint as held
      from public.credit_holds h join bounded_users b using (user_id)
     group by h.user_id
  ),
  allocations as (
    select a.user_id,
           coalesce(sum(a.amount) filter (where a.status = 'held'), 0)::bigint as held
      from public.credit_hold_allocations a join bounded_users b using (user_id)
     group by a.user_id
  ),
  hold_allocation_mismatches as (
    select h.user_id,
           (count(*) filter (
             where h.status = 'held'
               and coalesce(a.held_amount, 0) <> h.amount
           ))::bigint
           + (count(*) filter (
             where h.status <> 'held'
               and coalesce(a.held_amount, 0) <> 0
           ))::bigint as mismatch_count
      from public.credit_holds h
      join bounded_users b using (user_id)
      left join (
        select user_id, hold_id, sum(amount)::bigint as held_amount
          from public.credit_hold_allocations
         where status = 'held'
         group by user_id, hold_id
      ) a on a.user_id = h.user_id and a.hold_id = h.id
     group by h.user_id
  ),
  lot_allocation_mismatches as (
    select l.user_id,
           (count(*) filter (
             where l.reserved_credits <> coalesce(a.held_amount, 0)
           ))::bigint as mismatch_count
      from public.credit_lots l
      join bounded_users b using (user_id)
      left join (
        select user_id, lot_id, sum(amount)::bigint as held_amount
          from public.credit_hold_allocations
         where status = 'held'
         group by user_id, lot_id
      ) a on a.user_id = l.user_id and a.lot_id = l.id
     group by l.user_id
  ),
  latest_ledger as (
    select distinct on (e.user_id)
           e.user_id, e.balance_available_after, e.balance_reserved_after
      from public.credit_ledger e join bounded_users b using (user_id)
     order by e.user_id, e.id desc
  ),
  combined as (
    select b.user_id,
           coalesce(w.available_credits, 0)::bigint as wallet_available,
           coalesce(l.available, 0)::bigint as lot_available,
           coalesce(w.reserved_credits, 0)::bigint as wallet_reserved,
           coalesce(l.reserved, 0)::bigint as lot_reserved,
           coalesce(h.held, 0)::bigint as held_holds,
           coalesce(a.held, 0)::bigint as held_allocations,
           coalesce(ham.mismatch_count, 0)::bigint as hold_allocation_mismatches,
           coalesce(lam.mismatch_count, 0)::bigint as lot_allocation_mismatches,
           e.balance_available_after as ledger_available,
           e.balance_reserved_after as ledger_reserved
      from bounded_users b
      left join wallets w using (user_id)
      left join lots l using (user_id)
      left join holds h using (user_id)
      left join allocations a using (user_id)
      left join hold_allocation_mismatches ham using (user_id)
      left join lot_allocation_mismatches lam using (user_id)
      left join latest_ledger e using (user_id)
  )
  select c.user_id, c.wallet_available, c.lot_available,
         c.wallet_reserved, c.lot_reserved, c.held_holds, c.held_allocations,
         c.ledger_available, c.ledger_reserved,
         (c.wallet_available = c.lot_available
          and c.wallet_reserved = c.lot_reserved) as wallet_lots_match,
         (c.wallet_reserved = c.held_holds) as holds_match,
         (c.wallet_reserved = c.held_allocations
          and c.lot_reserved = c.held_allocations
          and c.hold_allocation_mismatches = 0
          and c.lot_allocation_mismatches = 0) as allocations_match,
         (c.ledger_available is not distinct from c.wallet_available
          and c.ledger_reserved is not distinct from c.wallet_reserved) as latest_ledger_matches,
         (c.wallet_available = c.lot_available
          and c.wallet_reserved = c.lot_reserved
          and c.wallet_reserved = c.held_holds
          and c.wallet_reserved = c.held_allocations
          and c.lot_reserved = c.held_allocations
          and c.hold_allocation_mismatches = 0
          and c.lot_allocation_mismatches = 0
          and c.ledger_available is not distinct from c.wallet_available
          and c.ledger_reserved is not distinct from c.wallet_reserved) as healthy
    from combined c
   order by c.user_id;
end;
$reconcile$;

revoke all on function public.audit_credit_wallet_reconciliation(uuid, integer)
  from public, anon, authenticated;
grant execute on function public.audit_credit_wallet_reconciliation(uuid, integer)
  to service_role;

comment on function public.audit_credit_wallet_reconciliation(uuid, integer) is
  'Read-only cross-check of wallet projections, lots, held holds, allocations and latest ledger balance. Reports drift; never repairs it.';
