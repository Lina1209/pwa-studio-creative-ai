-- Add keyset pagination to read-only credit wallet reconciliation.
-- The legacy two-argument RPC is retained, but now refuses to silently return
-- a partial result set; callers must use the paginated RPC for larger audits.

create or replace function public.audit_credit_wallet_reconciliation_page(
  p_user_id uuid default null,
  p_after_user_id uuid default null,
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
  healthy boolean,
  has_more boolean
)
language plpgsql
security definer
set search_path = pg_catalog, public
as $reconcile$
#variable_conflict use_column
begin
  if p_user_limit is null or p_user_limit not between 1 and 1000 then
    raise exception 'Reconciliation page limit must be between 1 and 1000'
      using errcode = '22023';
  end if;

  return query
  with target_users as (
    select w.user_id from public.credit_wallets w
     where (p_user_id is null or w.user_id = p_user_id)
        and (p_after_user_id is null or w.user_id > p_after_user_id)
    union
    select l.user_id from public.credit_lots l
     where (p_user_id is null or l.user_id = p_user_id)
        and (p_after_user_id is null or l.user_id > p_after_user_id)
    union
    select h.user_id from public.credit_holds h
     where (p_user_id is null or h.user_id = p_user_id)
        and (p_after_user_id is null or h.user_id > p_after_user_id)
    union
    -- Include ledger-only identities so a missing wallet projection is visible.
    select e.user_id from public.credit_ledger e
     where (p_user_id is null or e.user_id = p_user_id)
        and (p_after_user_id is null or e.user_id > p_after_user_id)
  ),
  bounded_users as (
    select t.user_id from target_users t order by t.user_id limit p_user_limit + 1
  ),
  page_users as (
    select b.user_id from bounded_users b order by b.user_id limit p_user_limit
  ),
  page_meta as (
    select count(*) > p_user_limit as has_more from bounded_users
  ),
  wallets as (
    select w.user_id, w.available_credits, w.reserved_credits
      from public.credit_wallets w join page_users b using (user_id)
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


revoke all on function public.audit_credit_wallet_reconciliation_page(uuid, uuid, integer)
  from public, anon, authenticated;
grant execute on function public.audit_credit_wallet_reconciliation_page(uuid, uuid, integer)
  to service_role;

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
as $legacy_reconcile$
begin
  if p_user_limit is null or p_user_limit not between 1 and 1000 then
    raise exception 'Reconciliation limit must be between 1 and 1000'
      using errcode = '22023';
  end if;

  if exists (
    select 1
      from public.audit_credit_wallet_reconciliation_page(p_user_id, null, p_user_limit) page
     where page.has_more
  ) then
    raise exception 'Reconciliation result is incomplete; use audit_credit_wallet_reconciliation_page with the last user_id as cursor'
      using errcode = '22023';
  end if;

  return query
  select page.user_id, page.wallet_available, page.lot_available,
         page.wallet_reserved, page.lot_reserved, page.held_holds,
         page.held_allocations, page.latest_ledger_available,
         page.latest_ledger_reserved, page.wallet_lots_match,
         page.holds_match, page.allocations_match,
         page.latest_ledger_matches, page.healthy
    from public.audit_credit_wallet_reconciliation_page(p_user_id, null, p_user_limit) page;
end;
$legacy_reconcile$;

revoke all on function public.audit_credit_wallet_reconciliation(uuid, integer)
  from public, anon, authenticated;
grant execute on function public.audit_credit_wallet_reconciliation(uuid, integer)
  to service_role;

comment on function public.audit_credit_wallet_reconciliation_page(uuid, uuid, integer) is
  'Keyset-paginated read-only financial reconciliation. has_more is true when another page exists; pass the last returned user_id as p_after_user_id. Never repairs balances.';
comment on function public.audit_credit_wallet_reconciliation(uuid, integer) is
  'Read-only reconciliation compatibility RPC. Raises when the requested result would be partial; use audit_credit_wallet_reconciliation_page for pagination.';
