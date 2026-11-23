-- Extend the existing one-user finance snapshot with refund settlement and
-- entitlement-compensation evidence. The wrapper and its base function execute
-- within one SQL statement snapshot; no source is read in a second RPC call.

alter function public.get_finance_integrity_audit_snapshot(uuid)
  rename to get_finance_integrity_audit_snapshot_base;

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
  base as (
    select public.get_finance_integrity_audit_snapshot_base(p_user_id) as data
  ),
  refunds_source as (
    select r.id, r.payment_order_id, r.user_id, r.provider_code,
           r.amount_minor, r.currency_code, r.idempotency_key, r.reason_code,
           r.status, r.provider_refund_id, r.requested_by,
           r.created_at, r.updated_at, r.submitted_at, r.settled_at, r.closed_at
      from public.payment_refunds r
     where r.user_id = p_user_id
  ),
  refunds_count as (select count(*)::bigint as total from refunds_source),
  refunds_page as (select * from refunds_source order by id limit 10001),
  refund_provider_events_source as (
    select e.id, e.provider_code, e.provider_event_id, e.refund_id,
           e.event_type, e.payload_sha256, e.amount_minor, e.currency_code,
           e.provider_refund_id, e.signature_verified, e.received_at
      from public.payment_refund_provider_events e
      join public.payment_refunds r on r.id = e.refund_id
     where r.user_id = p_user_id
  ),
  refund_provider_events_count as (
    select count(*)::bigint as total from refund_provider_events_source
  ),
  refund_provider_events_page as (
    select * from refund_provider_events_source order by id limit 20001
  ),
  refund_events_source as (
    select e.id, e.refund_id, e.actor_type, e.actor_user_id, e.event_type,
           e.previous_status, e.new_status, e.event_key, e.reason_code, e.occurred_at
      from public.payment_refund_events e
      join public.payment_refunds r on r.id = e.refund_id
     where r.user_id = p_user_id
  ),
  refund_events_count as (select count(*)::bigint as total from refund_events_source),
  refund_events_page as (select * from refund_events_source order by id limit 20001),
  refund_reconciliations_source as (
    select r.id, r.refund_id, r.payment_order_id, r.user_id, r.purchase_type,
           r.amount_minor, r.currency_code, r.status, r.created_at,
           r.reviewed_at, r.reviewed_by, r.resolution_code
      from public.payment_refund_reconciliations r
     where r.user_id = p_user_id
  ),
  refund_reconciliations_count as (
    select count(*)::bigint as total from refund_reconciliations_source
  ),
  refund_reconciliations_page as (
    select * from refund_reconciliations_source order by id limit 10001
  )
  select
    base.data || jsonb_build_object(
      'payment_refunds',
        coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from refunds_page p), '[]'::jsonb),
      'payment_refund_provider_events',
        coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from refund_provider_events_page p), '[]'::jsonb),
      'payment_refund_events',
        coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from refund_events_page p), '[]'::jsonb),
      'payment_refund_reconciliations',
        coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from refund_reconciliations_page p), '[]'::jsonb),
      'counts', (base.data -> 'counts') || jsonb_build_object(
        'payment_refunds', (select total from refunds_count),
        'payment_refund_provider_events', (select total from refund_provider_events_count),
        'payment_refund_events', (select total from refund_events_count),
        'payment_refund_reconciliations', (select total from refund_reconciliations_count)
      ),
      'limits', (base.data -> 'limits') || jsonb_build_object(
        'payment_refunds', 10000,
        'payment_refund_provider_events', 20000,
        'payment_refund_events', 20000,
        'payment_refund_reconciliations', 10000
      ),
      'complete', coalesce((base.data ->> 'complete')::boolean, false)
        and (select total from refunds_count) <= 10000
        and (select total from refund_provider_events_count) <= 20000
        and (select total from refund_events_count) <= 20000
        and (select total from refund_reconciliations_count) <= 10000
    )
  from base;
$function$;

revoke all on function public.get_finance_integrity_audit_snapshot_base(uuid)
  from public, anon, authenticated;
grant execute on function public.get_finance_integrity_audit_snapshot_base(uuid)
  to service_role;
revoke all on function public.get_finance_integrity_audit_snapshot(uuid)
  from public, anon, authenticated;
grant execute on function public.get_finance_integrity_audit_snapshot(uuid)
  to service_role;

comment on function public.get_finance_integrity_audit_snapshot(uuid) is
  'Read-only one-user finance snapshot including refund intents, verified refund events and pending entitlement compensation. Wrapper and base share one SQL statement snapshot; no refund or entitlement mutation occurs.';
