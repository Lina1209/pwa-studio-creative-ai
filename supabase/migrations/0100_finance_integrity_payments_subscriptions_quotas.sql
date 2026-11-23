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
    select l.id, l.user_id, l.operation_type, l.operation_key, l.delta_available,
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
    select l.id, l.user_id, l.lot_type, l.source_reference, l.idempotency_key,
           l.granted_credits, l.available_credits, l.reserved_credits,
           l.expires_at, l.created_at
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

  ,
  payment_orders_source as (
    select o.id, o.user_id, o.provider_code, o.merchant_reference,
           o.provider_payment_id, o.idempotency_key, o.amount_minor,
           o.currency_code, o.status, o.paid_at, o.closed_at, o.created_at
      from public.payment_orders o where o.user_id = p_user_id
  ),
  payment_orders_count as (select count(*)::bigint as total from payment_orders_source),
  payment_orders_page as (select * from payment_orders_source order by id limit 10001),
  payment_provider_events_source as (
    select e.id, e.provider_code, e.provider_event_id, e.payment_order_id,
           e.event_type, e.payload_sha256, e.signature_verified,
           e.processing_status, e.received_at, e.processed_at
      from public.payment_provider_events e
      join public.payment_orders o on o.id = e.payment_order_id
     where o.user_id = p_user_id
  ),
  payment_provider_events_count as (select count(*)::bigint as total from payment_provider_events_source),
  payment_provider_events_page as (select * from payment_provider_events_source order by id limit 20001),
  payment_order_events_source as (
    select e.id, e.payment_order_id, e.actor_type, e.event_type,
           e.previous_status, e.new_status, e.reason_code, e.occurred_at
      from public.payment_order_events e
      join public.payment_orders o on o.id = e.payment_order_id
     where o.user_id = p_user_id
  ),
  payment_order_events_count as (select count(*)::bigint as total from payment_order_events_source),
  payment_order_events_page as (select * from payment_order_events_source order by id limit 20001),
  purchase_items_source as (
    select i.payment_order_id, i.user_id, i.item_type,
           i.approved_credit_pack_version_id, i.approved_plan_version_id,
           i.sku_code, i.sku_version, i.amount_minor, i.currency_code,
           i.credit_quantity, i.credit_validity_days, i.plan_period_days
      from public.payment_order_purchase_items i where i.user_id = p_user_id
  ),
  purchase_items_count as (select count(*)::bigint as total from purchase_items_source),
  purchase_items_page as (select * from purchase_items_source order by payment_order_id limit 10001),
  fulfillment_source as (
    select f.id, f.payment_order_id, f.user_id, f.provider_code, f.amount_minor,
           f.currency_code, f.status, f.attempt_count, f.available_at,
           f.locked_at, f.lock_token, f.lease_expires_at, f.last_error_code,
           f.completed_at, f.created_at
      from public.payment_fulfillment_outbox f where f.user_id = p_user_id
  ),
  fulfillment_count as (select count(*)::bigint as total from fulfillment_source),
  fulfillment_page as (select * from fulfillment_source order by id limit 10001),
  assignments_source as (
    select a.id, a.user_id, a.approved_plan_version_id, a.assignment_source,
           a.source_reference, a.idempotency_key, a.status, a.starts_at,
           a.ends_at, a.created_by, a.created_at
      from public.user_plan_assignments a where a.user_id = p_user_id
  ),
  assignments_count as (select count(*)::bigint as total from assignments_source),
  assignments_page as (select * from assignments_source order by id limit 10001),
  assignment_events_source as (
    select e.id, e.assignment_id, e.user_id, e.event_type, e.actor_type,
           e.event_key, e.occurred_at
      from public.user_plan_assignment_events e where e.user_id = p_user_id
  ),
  assignment_events_count as (select count(*)::bigint as total from assignment_events_source),
  assignment_events_page as (select * from assignment_events_source order by id limit 20001),
  approved_plans_source as (
    select distinct p.id, p.plan_code, p.plan_version, p.period_days,
           p.credits_per_period, p.price_minor, p.currency, p.limits_json, p.features_json
      from public.approved_plan_versions p
      join public.user_plan_assignments a on a.approved_plan_version_id = p.id
     where a.user_id = p_user_id
  ),
  approved_plans_count as (select count(*)::bigint as total from approved_plans_source),
  approved_plans_page as (select * from approved_plans_source order by id limit 10001),
  quota_reservations_source as (
    select r.id, r.user_id, r.assignment_id, r.request_id, r.feature_key,
           r.period_start, r.reserved_units, r.operation_key, r.status,
           r.created_at, r.finished_at
      from public.plan_quota_reservations r where r.user_id = p_user_id
  ),
  quota_reservations_count as (select count(*)::bigint as total from quota_reservations_source),
  quota_reservations_page as (select * from quota_reservations_source order by id limit 20001),
  quota_events_source as (
    select e.id, e.reservation_id, e.user_id, e.event_type, e.event_key, e.occurred_at
      from public.plan_quota_events e where e.user_id = p_user_id
  ),
  quota_events_count as (select count(*)::bigint as total from quota_events_source),
  quota_events_page as (select * from quota_events_source order by id limit 40001)

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
        'source_reference', p.source_reference, 'idempotency_key', p.idempotency_key,
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

    'payment_orders', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from payment_orders_page p), '[]'::jsonb),
    'payment_provider_events', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from payment_provider_events_page p), '[]'::jsonb),
    'payment_order_events', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from payment_order_events_page p), '[]'::jsonb),
    'purchase_items', coalesce((select jsonb_agg(to_jsonb(p) order by p.payment_order_id) from purchase_items_page p), '[]'::jsonb),
    'fulfillment_outbox', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from fulfillment_page p), '[]'::jsonb),
    'plan_assignments', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from assignments_page p), '[]'::jsonb),
    'plan_assignment_events', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from assignment_events_page p), '[]'::jsonb),
    'approved_plans', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from approved_plans_page p), '[]'::jsonb),
    'quota_reservations', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from quota_reservations_page p), '[]'::jsonb),
    'quota_events', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from quota_events_page p), '[]'::jsonb),
    'counts', jsonb_build_object(
      'ledger', (select total from ledger_count),
      'holds', (select total from holds_count),
      'lots', (select total from lots_count),
      'allocations', (select total from allocations_count),
      'jobs', (select total from jobs_count),
      'provider_cost_events', (select total from costs_count),
      'payment_orders', (select total from payment_orders_count),
      'payment_provider_events', (select total from payment_provider_events_count),
      'payment_order_events', (select total from payment_order_events_count),
      'purchase_items', (select total from purchase_items_count),
      'fulfillment_outbox', (select total from fulfillment_count),
      'plan_assignments', (select total from assignments_count),
      'plan_assignment_events', (select total from assignment_events_count),
      'approved_plans', (select total from approved_plans_count),
      'quota_reservations', (select total from quota_reservations_count),
      'quota_events', (select total from quota_events_count)
    ),
    'limits', jsonb_build_object(
      'ledger', 10000, 'holds', 5000, 'lots', 5000,
      'allocations', 10000, 'jobs', 10000, 'provider_cost_events', 10000,
      'payment_orders', 10000, 'payment_provider_events', 20000,
      'payment_order_events', 20000, 'purchase_items', 10000,
      'fulfillment_outbox', 10000, 'plan_assignments', 10000,
      'plan_assignment_events', 20000, 'approved_plans', 10000,
      'quota_reservations', 20000, 'quota_events', 40000
    ),
    'complete', (
      (select total from ledger_count) <= 10000
      and (select total from holds_count) <= 5000
      and (select total from lots_count) <= 5000
      and (select total from allocations_count) <= 10000
      and (select total from jobs_count) <= 10000
      and (select total from costs_count) <= 10000

      and (select total from payment_orders_count) <= 10000
      and (select total from payment_provider_events_count) <= 20000
      and (select total from payment_order_events_count) <= 20000
      and (select total from purchase_items_count) <= 10000
      and (select total from fulfillment_count) <= 10000
      and (select total from assignments_count) <= 10000
      and (select total from assignment_events_count) <= 20000
      and (select total from approved_plans_count) <= 10000
      and (select total from quota_reservations_count) <= 20000
      and (select total from quota_events_count) <= 40000
    )
  );
$function$;

revoke all on function public.get_finance_integrity_audit_snapshot(uuid)
  from public, anon, authenticated;
grant execute on function public.get_finance_integrity_audit_snapshot(uuid)
  to service_role;

comment on function public.get_finance_integrity_audit_snapshot(uuid) is
  'Read-only one-user finance integrity snapshot. All source arrays are taken in one SQL statement snapshot. Returns explicit counts, hard limits and complete=false on truncation; never repairs financial data.';
