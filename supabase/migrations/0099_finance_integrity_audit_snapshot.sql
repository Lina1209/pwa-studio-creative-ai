-- Read-only, bounded, single-statement finance audit snapshot.
-- One RPC call returns every source for one user from the same PostgreSQL statement
-- snapshot. If any source exceeds its cap, complete=false and the caller must not
-- report a healthy audit. No writes or financial lifecycle operations occur.

create or replace function public.get_finance_integrity_audit_snapshot(
  p_user_id uuid
)
returns jsonb
language sql
stable
security definer
set search_path = pg_catalog, public
as $function$
  with
  wallet as (
    select jsonb_build_object(
      'available_credits', w.available_credits,
      'reserved_credits', w.reserved_credits
    ) as data
    from public.credit_wallets w
    where w.user_id = p_user_id
  ),
  ledger_source as (
    select l.id, l.user_id, l.operation_type, l.delta_available,
           l.delta_reserved, l.balance_available_after,
           l.balance_reserved_after, l.created_at
      from public.credit_ledger l
     where l.user_id = p_user_id
     order by l.id
  ),
  ledger_count as (select count(*)::bigint as total from ledger_source),
  ledger_page as (
    select * from ledger_source order by id limit 10000
  ),
  holds_source as (
    select h.id, h.user_id, h.job_id, h.amount, h.status
      from public.credit_holds h where h.user_id = p_user_id
  ),
  holds_count as (select count(*)::bigint as total from holds_source),
  holds_page as (select * from holds_source order by id limit 5000),
  lots_source as (
    select l.id, l.user_id, l.lot_type, l.granted_credits,
           l.available_credits, l.reserved_credits, l.expires_at, l.created_at
      from public.credit_lots l where l.user_id = p_user_id
  ),
  lots_count as (select count(*)::bigint as total from lots_source),
  lots_page as (select * from lots_source order by id limit 5001),
  allocations_source as (
    select a.id, a.user_id, a.hold_id, a.lot_id, a.amount, a.status
      from public.credit_hold_allocations a where a.user_id = p_user_id
  ),
  allocations_count as (select count(*)::bigint as total from allocations_source),
  allocations_page as (
    select * from allocations_source order by id limit 10001
  ),
  jobs_source as (
    select j.id, j.user_id, j.job_type, j.provider, j.model, j.status
      from public.generation_jobs j where j.user_id = p_user_id
  ),
  jobs_count as (select count(*)::bigint as total from jobs_source),
  jobs_page as (select * from jobs_source order by id limit 10001),
  costs_source as (
    select e.id, e.user_id, e.job_id, e.operation_key, e.provider, e.model,
           e.provider_usage_id, e.cost_usd, e.cost_source, e.created_at
      from public.generation_provider_cost_events e where e.user_id = p_user_id
  ),
  costs_count as (select count(*)::bigint as total from costs_source),
  costs_page as (select * from costs_source order by id limit 10001)
  select jsonb_build_object(
    'user_id', p_user_id,
    'wallet', coalesce((select data from wallet), '{}'::jsonb),
    'ledger', coalesce((
      select jsonb_agg(jsonb_build_object(
        'entry_id', p.id, 'user_id', p.user_id,
        'operation_type', p.operation_type, 'operation_key', p.operation_key,
        'delta_available', p.delta_available, 'delta_reserved', p.delta_reserved,
        'balance_available_after', p.balance_available_after,
        'balance_reserved_after', p.balance_reserved_after,
        'created_at', p.created_at
      ) order by p.id) from ledger_page p
    ), '[]'::jsonb),
    'holds', coalesce((
      select jsonb_agg(jsonb_build_object(
        'hold_id', p.id, 'user_id', p.user_id, 'job_id', p.job_id,
        'amount', p.amount, 'status', p.status
      ) order by p.id) from holds_page p
    ), '[]'::jsonb),
    'lots', coalesce((
      select jsonb_agg(jsonb_build_object(
        'lot_id', p.id, 'user_id', p.user_id, 'lot_type', p.lot_type,
        'granted_credits', p.granted_credits,
        'available_credits', p.available_credits,
        'reserved_credits', p.reserved_credits,
        'expires_at', p.expires_at, 'created_at', p.created_at
      ) order by p.id) from lots_page p
    ), '[]'::jsonb),
    'allocations', coalesce((
      select jsonb_agg(jsonb_build_object(
        'allocation_id', p.id, 'user_id', p.user_id,
        'hold_id', p.hold_id, 'lot_id', p.lot_id,
        'amount', p.amount, 'status', p.status
      ) order by p.id) from allocations_page p
    ), '[]'::jsonb),
    'jobs', coalesce((
      select jsonb_agg(jsonb_build_object(
        'job_id', p.id, 'user_id', p.user_id, 'job_type', p.job_type,
        'provider', p.provider, 'model', p.model, 'status', p.status
      ) order by p.id) from jobs_page p
    ), '[]'::jsonb),
    'provider_cost_events', coalesce((
      select jsonb_agg(jsonb_build_object(
        'event_id', p.id, 'user_id', p.user_id, 'job_id', p.job_id,
        'operation_key', p.operation_key, 'provider', p.provider,
        'model', p.model, 'provider_usage_id', p.provider_usage_id,
        'cost_usd', p.cost_usd, 'cost_source', p.cost_source,
        'created_at', p.created_at
      ) order by p.id) from costs_page p
    ), '[]'::jsonb),
    'counts', jsonb_build_object(
      'ledger', (select total from ledger_count),
      'holds', (select total from holds_count),
      'lots', (select total from lots_count),
      'allocations', (select total from allocations_count),
      'jobs', (select total from jobs_count),
      'provider_cost_events', (select total from costs_count)
    ),
    'limits', jsonb_build_object(
      'ledger', 10000, 'holds', 5000, 'lots', 5000,
      'allocations', 10000, 'jobs', 10000, 'provider_cost_events', 10000
    ),
    'complete', (
      (select total from ledger_count) <= 10000
      and (select total from holds_count) <= 5000
      and (select total from lots_count) <= 5000
      and (select total from allocations_count) <= 10000
      and (select total from jobs_count) <= 10000
      and (select total from costs_count) <= 10000
    )
  );
$function$;

revoke all on function public.get_finance_integrity_audit_snapshot(uuid)
  from public, anon, authenticated;
grant execute on function public.get_finance_integrity_audit_snapshot(uuid)
  to service_role;

comment on function public.get_finance_integrity_audit_snapshot(uuid) is
  'Read-only one-user finance integrity snapshot. All source arrays are taken in one SQL statement snapshot. Returns explicit counts, hard limits and complete=false on truncation; never repairs financial data.';
