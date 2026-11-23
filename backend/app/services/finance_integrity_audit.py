"""Pure, read-only finance integrity checks over explicitly supplied snapshots.

The module does not fetch data, mutate balances, or repair financial records.
Callers must only mark an audit complete when every source has been fully paginated.
"""
from collections import defaultdict
from hashlib import md5
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("naive_timestamp")
    return parsed.astimezone(timezone.utc)


def _money(value: Any, *, nullable: bool = False) -> Decimal | None:
    if value is None and nullable:
        return None
    if value is None or isinstance(value, bool):
        raise ValueError("invalid_cost")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid_cost") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid_cost")
    return amount


def _finding(code: str, severity: str, **details: Any) -> dict[str, Any]:
    # Findings intentionally contain identifiers/codes only, never raw metadata.
    return {"code": code, "severity": severity, **details}


def audit_finance_integrity(
    *,
    ledger_entries: list[dict[str, Any]],
    wallets: dict[str, dict[str, Any]],
    generation_jobs: list[dict[str, Any]],
    provider_cost_events: list[dict[str, Any]],
    credit_holds: list[dict[str, Any]] | None = None,
    credit_lots: list[dict[str, Any]] | None = None,
    hold_allocations: list[dict[str, Any]] | None = None,
    payment_orders: list[dict[str, Any]] | None = None,
    payment_provider_events: list[dict[str, Any]] | None = None,
    payment_order_events: list[dict[str, Any]] | None = None,
    purchase_items: list[dict[str, Any]] | None = None,
    fulfillment_outbox: list[dict[str, Any]] | None = None,
    plan_assignments: list[dict[str, Any]] | None = None,
    plan_assignment_events: list[dict[str, Any]] | None = None,
    approved_plans: list[dict[str, Any]] | None = None,
    quota_reservations: list[dict[str, Any]] | None = None,
    quota_events: list[dict[str, Any]] | None = None,
    opening_balances: dict[str, tuple[int, int]] | None = None,
    complete: bool = False,
) -> dict[str, Any]:
    """Audit supplied snapshots; incomplete input can never produce healthy status.

    Ledger entries require entry_id, user_id, delta_available, delta_reserved,
    balance_available_after, balance_reserved_after, and timezone-aware created_at.
    Wallets are keyed by user_id. Jobs require job_id; optional
    expects_provider_cost=True enables missing-cost detection for that job.
    Cost events require event_id, job_id, operation_key, provider,
    provider_usage_id, cost_source, and cost_usd.
    """
    if not isinstance(ledger_entries, list) or not isinstance(wallets, dict):
        raise ValueError("invalid_audit_input")
    if not isinstance(generation_jobs, list) or not isinstance(provider_cost_events, list):
        raise ValueError("invalid_audit_input")
    check_holds = credit_holds is not None
    check_lots = credit_lots is not None
    check_allocations = hold_allocations is not None
    commerce_sources = {
        "payment_orders": payment_orders,
        "payment_provider_events": payment_provider_events,
        "payment_order_events": payment_order_events,
        "purchase_items": purchase_items,
        "fulfillment_outbox": fulfillment_outbox,
        "plan_assignments": plan_assignments,
        "plan_assignment_events": plan_assignment_events,
        "approved_plans": approved_plans,
        "quota_reservations": quota_reservations,
        "quota_events": quota_events,
    }
    check_commerce = all(rows is not None for rows in commerce_sources.values())
    credit_holds = [] if credit_holds is None else credit_holds
    credit_lots = [] if credit_lots is None else credit_lots
    hold_allocations = [] if hold_allocations is None else hold_allocations
    payment_orders = [] if payment_orders is None else payment_orders
    payment_provider_events = [] if payment_provider_events is None else payment_provider_events
    payment_order_events = [] if payment_order_events is None else payment_order_events
    purchase_items = [] if purchase_items is None else purchase_items
    fulfillment_outbox = [] if fulfillment_outbox is None else fulfillment_outbox
    plan_assignments = [] if plan_assignments is None else plan_assignments
    plan_assignment_events = [] if plan_assignment_events is None else plan_assignment_events
    approved_plans = [] if approved_plans is None else approved_plans
    quota_reservations = [] if quota_reservations is None else quota_reservations
    quota_events = [] if quota_events is None else quota_events
    if not all(isinstance(rows, list) for rows in (
        credit_holds, credit_lots, hold_allocations, *commerce_sources.values()
    )):
        raise ValueError("invalid_audit_input")
    if not isinstance(complete, bool):
        raise ValueError("invalid_completeness_flag")

    findings: list[dict[str, Any]] = []
    ledger_by_user: dict[str, list[tuple[datetime, int, dict[str, Any]]]] = defaultdict(list)
    seen_ledger_ids: set[int] = set()
    seen_ledger_operations: set[tuple[str, str]] = set()
    for raw in ledger_entries:
        try:
            if not isinstance(raw, dict):
                raise ValueError("invalid_row")
            user_id, entry_id = raw.get("user_id"), raw.get("entry_id")
            fields = (
                "delta_available", "delta_reserved",
                "balance_available_after", "balance_reserved_after",
            )
            if not isinstance(user_id, str) or not user_id:
                raise ValueError("invalid_user_id")
            if not _integer(entry_id) or entry_id < 1:
                raise ValueError("invalid_entry_id")
            if any(not _integer(raw.get(field)) for field in fields):
                raise ValueError("invalid_balance_integer")
            operation_type, operation_key = raw.get("operation_type"), raw.get("operation_key")
            if operation_type not in {"grant", "reserve", "capture", "release", "refund", "adjustment"}:
                raise ValueError("invalid_operation_type")
            if not isinstance(operation_key, str) or not operation_key:
                raise ValueError("invalid_operation_key")
            if raw["delta_available"] == 0 and raw["delta_reserved"] == 0:
                raise ValueError("zero_ledger_delta")
            if entry_id in seen_ledger_ids:
                findings.append(_finding("duplicate_ledger_entry_id", "critical", user_id=user_id, entry_id=entry_id))
            seen_ledger_ids.add(entry_id)
            operation = (user_id, operation_key)
            if operation in seen_ledger_operations:
                findings.append(_finding("duplicate_ledger_operation_key", "critical", user_id=user_id, entry_id=entry_id))
            seen_ledger_operations.add(operation)
            if raw["balance_available_after"] < 0 or raw["balance_reserved_after"] < 0:
                findings.append(_finding("negative_ledger_balance", "critical", user_id=user_id, entry_id=entry_id))
            created = _timestamp(raw.get("created_at"))
            ledger_by_user[user_id].append((created, entry_id, raw))
        except (ValueError, TypeError, AttributeError):
            findings.append(_finding("invalid_ledger_row", "critical"))

    opening_balances = opening_balances or {}
    for user_id, entries in ledger_by_user.items():
        # Identity IDs are allocated when the ledger insert occurs. Lifecycle RPCs
        # serialize mutations on the wallet row, so ID order is the accounting order;
        # created_at uses transaction-start time and can be misleading under concurrency.
        entries.sort(key=lambda item: item[1])
        previous: tuple[int, int] | None = opening_balances.get(user_id)
        if previous is None and entries:
            first = entries[0][2]
            inferred = (
                first["balance_available_after"] - first["delta_available"],
                first["balance_reserved_after"] - first["delta_reserved"],
            )
            if min(inferred) < 0:
                findings.append(_finding("invalid_initial_ledger_transition", "critical", user_id=user_id, entry_id=entries[0][1]))
            else:
                findings.append(_finding("opening_balance_unverified", "warning", user_id=user_id))
        for _, entry_id, row in entries:
            current = (row["balance_available_after"], row["balance_reserved_after"])
            if previous is not None:
                expected = (
                    previous[0] + row["delta_available"],
                    previous[1] + row["delta_reserved"],
                )
                if current != expected:
                    findings.append(_finding("ledger_discontinuity", "critical", user_id=user_id, entry_id=entry_id))
            previous = current

        wallet = wallets.get(user_id)
        if wallet is None:
            findings.append(_finding("wallet_snapshot_missing", "warning", user_id=user_id))
        elif previous is not None:
            available, reserved = wallet.get("available_credits"), wallet.get("reserved_credits")
            if not _integer(available) or not _integer(reserved):
                findings.append(_finding("invalid_wallet_snapshot", "critical", user_id=user_id))
            elif (available, reserved) != previous:
                findings.append(_finding("wallet_ledger_mismatch", "critical", user_id=user_id))

    for user_id in wallets:
        if user_id not in ledger_by_user:
            findings.append(_finding("ledger_history_missing", "warning", user_id=user_id))

    # Reconcile source-separated lots, holds and their allocations. These
    # checks are intentionally independent of the aggregate wallet/ledger checks.
    lot_map: dict[str, dict[str, Any]] = {}
    lot_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for lot in credit_lots:
        try:
            if not isinstance(lot, dict):
                raise ValueError("invalid_lot")
            lot_id, owner = lot.get("lot_id"), lot.get("user_id")
            amounts = [lot.get("granted_credits"), lot.get("available_credits"), lot.get("reserved_credits")]
            if not isinstance(lot_id, str) or not lot_id or not isinstance(owner, str) or not owner:
                raise ValueError("invalid_lot_identity")
            if any(not _integer(value) or value < 0 for value in amounts) or amounts[0] <= 0:
                raise ValueError("invalid_lot_amount")
            if amounts[1] + amounts[2] > amounts[0]:
                findings.append(_finding("lot_balance_exceeds_grant", "critical", user_id=owner, lot_id=lot_id))
            if lot_id in lot_map:
                findings.append(_finding("duplicate_credit_lot", "critical", user_id=owner, lot_id=lot_id))
            lot_map[lot_id] = lot
            totals = lot_totals[owner]
            totals[0] += amounts[1]
            totals[1] += amounts[2]
            totals[2] += amounts[0]
        except (ValueError, TypeError):
            findings.append(_finding("invalid_credit_lot", "critical"))

    for owner, totals in lot_totals.items() if check_lots else ():
        wallet = wallets.get(owner)
        if wallet is None:
            findings.append(_finding("lot_wallet_snapshot_missing", "warning", user_id=owner))
            continue
        available, reserved = wallet.get("available_credits"), wallet.get("reserved_credits")
        if _integer(available) and _integer(reserved) and (totals[0], totals[1]) != (available, reserved):
            findings.append(_finding("lot_wallet_projection_mismatch", "critical", user_id=owner))

    hold_map: dict[str, dict[str, Any]] = {}
    for hold in credit_holds:
        try:
            if not isinstance(hold, dict):
                raise ValueError("invalid_hold")
            hold_id, owner, amount, state = hold.get("hold_id"), hold.get("user_id"), hold.get("amount"), hold.get("status")
            if not isinstance(hold_id, str) or not hold_id or not isinstance(owner, str) or not owner:
                raise ValueError("invalid_hold_identity")
            if not _integer(amount) or amount <= 0 or state not in {"held", "captured", "released"}:
                raise ValueError("invalid_hold_amount_or_status")
            if hold_id in hold_map:
                findings.append(_finding("duplicate_credit_hold", "critical", user_id=owner, hold_id=hold_id))
            hold_map[hold_id] = hold
        except (ValueError, TypeError):
            findings.append(_finding("invalid_credit_hold", "critical"))

    allocation_sums: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"held": 0, "captured": 0, "released": 0})
    lot_held_allocations: dict[str, int] = defaultdict(int)
    lot_captured_allocations: dict[str, int] = defaultdict(int)
    seen_allocations: set[str] = set()
    seen_hold_lots: set[tuple[str, str]] = set()
    for allocation in hold_allocations if check_allocations else ():
        try:
            if not isinstance(allocation, dict):
                raise ValueError("invalid_allocation")
            allocation_id, owner = allocation.get("allocation_id"), allocation.get("user_id")
            hold_id, lot_id = allocation.get("hold_id"), allocation.get("lot_id")
            amount, state = allocation.get("amount"), allocation.get("status")
            if (not isinstance(allocation_id, str) or not allocation_id
                or not isinstance(owner, str) or not owner
                or not isinstance(hold_id, str) or not isinstance(lot_id, str)
                or not _integer(amount) or amount <= 0
                or state not in {"held", "captured", "released"}):
                raise ValueError("invalid_allocation_fields")
            if allocation_id in seen_allocations:
                findings.append(_finding("duplicate_hold_allocation", "critical", user_id=owner))
            seen_allocations.add(allocation_id)
            pair = (hold_id, lot_id)
            if pair in seen_hold_lots:
                findings.append(_finding("duplicate_hold_lot_allocation", "critical", user_id=owner, hold_id=hold_id))
            seen_hold_lots.add(pair)
            hold = hold_map.get(hold_id)
            lot = lot_map.get(lot_id)
            if hold is None or lot is None:
                findings.append(_finding("orphan_hold_allocation", "critical", user_id=owner, hold_id=hold_id, lot_id=lot_id))
                continue
            if hold.get("user_id") != owner or lot.get("user_id") != owner:
                findings.append(_finding("hold_allocation_owner_mismatch", "critical", user_id=owner, hold_id=hold_id, lot_id=lot_id))
            allocation_sums[(hold_id, state)][state] += amount
            if state == "held":
                lot_held_allocations[lot_id] += amount
            elif state == "captured":
                lot_captured_allocations[lot_id] += amount
        except (ValueError, TypeError):
            findings.append(_finding("invalid_hold_allocation", "critical"))

    for hold_id, hold in hold_map.items() if check_holds and check_allocations else ():
        expected_state = hold["status"]
        totals = allocation_sums.get((hold_id, expected_state), {})
        actual = totals.get(expected_state, 0)
        if actual != hold["amount"]:
            findings.append(_finding("hold_allocation_total_mismatch", "critical", user_id=hold["user_id"], hold_id=hold_id))
        for other_state in {"held", "captured", "released"} - {expected_state}:
            if allocation_sums.get((hold_id, other_state), {}).get(other_state, 0):
                findings.append(_finding("hold_allocation_status_mismatch", "critical", user_id=hold["user_id"], hold_id=hold_id))

    for lot_id, lot in lot_map.items() if check_lots and check_allocations else ():
        if lot_held_allocations.get(lot_id, 0) != lot["reserved_credits"]:
            findings.append(_finding("lot_allocation_total_mismatch", "critical", user_id=lot["user_id"], lot_id=lot_id))
        consumed_and_remaining = (
            lot["available_credits"]
            + lot["reserved_credits"]
            + lot_captured_allocations.get(lot_id, 0)
        )
        if consumed_and_remaining > lot["granted_credits"]:
            findings.append(_finding("lot_consumption_exceeds_grant", "critical", user_id=lot["user_id"], lot_id=lot_id))

    for owner, wallet in wallets.items():
        if not isinstance(wallet, dict):
            findings.append(_finding("invalid_wallet_snapshot", "critical", user_id=owner))
            continue
        available, reserved = wallet.get("available_credits"), wallet.get("reserved_credits")
        if check_holds and _integer(reserved):
            held_total = sum(h["amount"] for h in hold_map.values() if h["user_id"] == owner and h["status"] == "held")
            if held_total != reserved:
                findings.append(_finding("wallet_hold_total_mismatch", "critical", user_id=owner))

    job_map: dict[str, dict[str, Any]] = {}
    for job in generation_jobs:
        if not isinstance(job, dict) or not isinstance(job.get("job_id"), str) or not job["job_id"]:
            findings.append(_finding("invalid_generation_job", "critical"))
            continue
        if job["job_id"] in job_map:
            findings.append(_finding("duplicate_generation_job", "critical", job_id=job["job_id"]))
        job_map[job["job_id"]] = job

    seen_event_ids: set[Any] = set()
    seen_operation_keys: set[tuple[str, str]] = set()
    seen_provider_usage: set[tuple[str, str]] = set()
    event_counts: dict[str, int] = defaultdict(int)
    for event in provider_cost_events:
        if not isinstance(event, dict):
            findings.append(_finding("invalid_provider_cost_event", "critical"))
            continue
        event_id, job_id = event.get("event_id"), event.get("job_id")
        operation_key, provider = event.get("operation_key"), event.get("provider")
        model, event_user_id = event.get("model"), event.get("user_id")
        usage_id, source = event.get("provider_usage_id"), event.get("cost_source")
        if (
            not _integer(event_id) or event_id < 1
            or not isinstance(job_id, str) or job_id not in job_map
            or not isinstance(operation_key, str) or not operation_key
            or not isinstance(provider, str) or not provider
            or not isinstance(model, str) or not model
            or not isinstance(event_user_id, str) or not event_user_id
        ):
            findings.append(_finding("orphan_or_invalid_provider_cost_event", "critical"))
            continue
        job = job_map[job_id]
        if (
            job.get("user_id") != event_user_id
            or job.get("provider") != provider
            or job.get("model") != model
        ):
            findings.append(_finding("provider_cost_job_identity_mismatch", "critical", job_id=job_id))
        if event_id in seen_event_ids:
            findings.append(_finding("duplicate_provider_cost_event_id", "critical", job_id=job_id))
        seen_event_ids.add(event_id)
        operation = (job_id, operation_key)
        if operation in seen_operation_keys:
            findings.append(_finding("duplicate_provider_operation_key", "critical", job_id=job_id))
        seen_operation_keys.add(operation)
        if usage_id is not None:
            if not isinstance(usage_id, str) or not usage_id:
                findings.append(_finding("invalid_provider_usage_id", "critical", job_id=job_id))
            else:
                usage = (provider, usage_id)
                if usage in seen_provider_usage:
                    findings.append(_finding("duplicate_provider_usage_id", "critical", job_id=job_id))
                seen_provider_usage.add(usage)
        try:
            cost = _money(event.get("cost_usd"), nullable=(source == "unknown"))
            if source not in {"reported", "estimated", "unknown"}:
                raise ValueError("invalid_cost_source")
            if (source == "unknown") != (cost is None):
                raise ValueError("cost_source_mismatch")
        except (ValueError, TypeError):
            findings.append(_finding("invalid_provider_cost_evidence", "critical", job_id=job_id))
        event_counts[job_id] += 1

    for job_id, job in job_map.items():
        if job.get("expects_provider_cost") is True and event_counts[job_id] == 0:
            findings.append(_finding("expected_provider_cost_missing", "warning", job_id=job_id))


    # Reconcile immutable payment intent, provider settlement evidence,
    # fulfillment and the resulting credit lot / plan assignment.
    if check_commerce:
        orders_by_id: dict[str, dict[str, Any]] = {}
        order_keys: set[tuple[str, str]] = set()
        merchant_keys: set[tuple[str, str]] = set()
        provider_payment_keys: set[tuple[str, str]] = set()
        for order in payment_orders:
            try:
                oid, owner = order.get("id"), order.get("user_id")
                provider, idem = order.get("provider_code"), order.get("idempotency_key")
                merchant, status = order.get("merchant_reference"), order.get("status")
                amount, currency = order.get("amount_minor"), order.get("currency_code")
                if (not isinstance(oid, str) or not oid or not isinstance(owner, str) or not owner
                    or not isinstance(provider, str) or not provider
                    or not isinstance(idem, str) or not idem
                    or not isinstance(merchant, str) or not merchant
                    or not _integer(amount) or amount <= 0
                    or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)
                    or status not in {"created", "pending", "succeeded", "failed", "cancelled", "partially_refunded", "refunded"}):
                    raise ValueError("invalid_payment_order")
                if oid in orders_by_id:
                    findings.append(_finding("duplicate_payment_order_id", "critical", payment_order_id=oid))
                orders_by_id[oid] = order
                for seen, key, code in (
                    (order_keys, (owner, idem), "duplicate_payment_idempotency_key"),
                    (merchant_keys, (provider, merchant), "duplicate_payment_merchant_reference"),
                ):
                    if key in seen:
                        findings.append(_finding(code, "critical", payment_order_id=oid))
                    seen.add(key)
                provider_payment_id = order.get("provider_payment_id")
                if provider_payment_id:
                    key = (provider, provider_payment_id)
                    if key in provider_payment_keys:
                        findings.append(_finding("duplicate_provider_payment_id", "critical", payment_order_id=oid))
                    provider_payment_keys.add(key)
                paid_at, closed_at = order.get("paid_at"), order.get("closed_at")
                if status in {"succeeded", "partially_refunded"} and (not paid_at or closed_at):
                    findings.append(_finding("invalid_settled_payment_timestamps", "critical", payment_order_id=oid))
                if status in {"failed", "cancelled", "refunded"} and not closed_at:
                    findings.append(_finding("invalid_closed_payment_timestamps", "critical", payment_order_id=oid))
                if status in {"created", "pending"} and (paid_at or closed_at):
                    findings.append(_finding("invalid_open_payment_timestamps", "critical", payment_order_id=oid))
                if status in {"partially_refunded", "refunded"}:
                    findings.append(_finding("refund_amounts_not_auditable", "warning", payment_order_id=oid))
            except (AttributeError, ValueError, TypeError):
                findings.append(_finding("invalid_payment_order", "critical"))

        purchases: dict[str, dict[str, Any]] = {}
        for item in purchase_items:
            order_id = item.get("payment_order_id") if isinstance(item, dict) else None
            if not isinstance(order_id, str) or order_id in purchases:
                findings.append(_finding("duplicate_or_invalid_purchase_snapshot", "critical"))
                continue
            purchases[order_id] = item
            order = orders_by_id.get(order_id)
            if order is None:
                findings.append(_finding("orphan_payment_purchase_snapshot", "critical", payment_order_id=order_id))
                continue
            if (item.get("user_id") != order.get("user_id")
                or item.get("amount_minor") != order.get("amount_minor")
                or str(item.get("currency_code", "")).strip() != str(order.get("currency_code", "")).strip()):
                findings.append(_finding("payment_purchase_snapshot_mismatch", "critical", payment_order_id=order_id))
            if item.get("item_type") not in {"credit_pack", "subscription"}:
                findings.append(_finding("invalid_payment_purchase_type", "critical", payment_order_id=order_id))

        outbox_by_order: dict[str, dict[str, Any]] = {}
        for row in fulfillment_outbox:
            oid = row.get("payment_order_id") if isinstance(row, dict) else None
            if not isinstance(oid, str) or oid in outbox_by_order:
                findings.append(_finding("duplicate_or_invalid_payment_fulfillment", "critical"))
                continue
            outbox_by_order[oid] = row
            order = orders_by_id.get(oid)
            if order is None:
                findings.append(_finding("orphan_payment_fulfillment", "critical", payment_order_id=oid))
                continue
            identity = ("user_id", "provider_code", "amount_minor", "currency_code")
            if any(row.get(field) != order.get(field) for field in identity):
                findings.append(_finding("payment_fulfillment_identity_mismatch", "critical", payment_order_id=oid))
            if row.get("status") not in {"queued", "processing", "completed", "failed", "manual_review"}:
                findings.append(_finding("invalid_payment_fulfillment_status", "critical", payment_order_id=oid))
            elif row.get("status") in {"failed", "manual_review", "queued", "processing"}:
                findings.append(_finding("payment_fulfillment_not_completed", "warning", payment_order_id=oid))

        order_events_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in payment_order_events:
            if not isinstance(event, dict) or event.get("payment_order_id") not in orders_by_id:
                findings.append(_finding("orphan_payment_order_event", "critical"))
                continue
            order_events_by_order[event["payment_order_id"]].append(event)
        provider_events_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
        provider_event_keys: set[tuple[str, str]] = set()
        for event in payment_provider_events:
            if not isinstance(event, dict):
                findings.append(_finding("invalid_payment_provider_event", "critical"))
                continue
            oid = event.get("payment_order_id")
            provider, event_id = event.get("provider_code"), event.get("provider_event_id")
            order = orders_by_id.get(oid)
            if order is None:
                findings.append(_finding("orphan_payment_provider_event", "critical"))
                continue
            if not isinstance(provider, str) or provider != order.get("provider_code"):
                findings.append(_finding("payment_provider_event_identity_mismatch", "critical", payment_order_id=oid))
            key = (str(provider), str(event_id))
            if key in provider_event_keys:
                findings.append(_finding("duplicate_payment_provider_event", "critical", payment_order_id=oid))
            provider_event_keys.add(key)
            if event.get("signature_verified") is not True or not isinstance(event.get("payload_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", event["payload_sha256"]):
                findings.append(_finding("unverified_payment_provider_event", "critical", payment_order_id=oid))
            if event.get("processing_status") != "processed" or not event.get("processed_at"):
                findings.append(_finding("payment_provider_event_unprocessed", "warning", payment_order_id=oid))
            provider_events_by_order[oid].append(event)

        assignment_by_order: dict[str, dict[str, Any]] = {}
        assignment_by_id: dict[str, dict[str, Any]] = {}
        plan_by_id = {p.get("id"): p for p in approved_plans if isinstance(p, dict)}
        for assignment in plan_assignments:
            if not isinstance(assignment, dict):
                findings.append(_finding("invalid_plan_assignment", "critical"))
                continue
            aid = assignment.get("id")
            if not isinstance(aid, str) or not aid or aid in assignment_by_id:
                findings.append(_finding("duplicate_or_invalid_plan_assignment", "critical"))
                continue
            assignment_by_id[aid] = assignment
            ref = assignment.get("source_reference")
            if isinstance(ref, str) and ref.startswith("payment-order:"):
                oid = ref.removeprefix("payment-order:")
                if oid in assignment_by_order:
                    findings.append(_finding("duplicate_payment_plan_assignment", "critical", payment_order_id=oid))
                assignment_by_order[oid] = assignment
                order, item = orders_by_id.get(oid), purchases.get(oid)
                if (order is None or order.get("status") not in {"succeeded", "partially_refunded", "refunded"}
                    or item is None or item.get("item_type") != "subscription"
                    or item.get("approved_plan_version_id") != assignment.get("approved_plan_version_id")
                    or assignment.get("user_id") != (order or {}).get("user_id")):
                    findings.append(_finding("payment_plan_assignment_mismatch", "critical", payment_order_id=oid))
                if assignment.get("assignment_source") != "verified_payment":
                    findings.append(_finding("payment_plan_assignment_source_mismatch", "critical", payment_order_id=oid))
            if assignment.get("approved_plan_version_id") not in plan_by_id:
                findings.append(_finding("assigned_plan_snapshot_missing", "critical", assignment_id=aid))

        assignment_events_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        assignment_event_keys: set[tuple[str, str]] = set()
        for event in plan_assignment_events:
            if not isinstance(event, dict) or event.get("assignment_id") not in assignment_by_id:
                findings.append(_finding("orphan_plan_assignment_event", "critical"))
                continue
            aid = event["assignment_id"]
            assignment = assignment_by_id[aid]
            if event.get("user_id") != assignment.get("user_id"):
                findings.append(_finding("plan_assignment_event_owner_mismatch", "critical", assignment_id=aid))
            key = (aid, str(event.get("event_key")))
            if key in assignment_event_keys:
                findings.append(_finding("duplicate_plan_assignment_event_key", "critical", assignment_id=aid))
            assignment_event_keys.add(key)
            if event.get("event_type") not in {"created", "activated", "scheduled", "expired", "cancelled", "revoked"}:
                findings.append(_finding("invalid_plan_assignment_event", "critical", assignment_id=aid))
            assignment_events_by_id[aid].append(event)
        for aid, assignment in assignment_by_id.items():
            if not any(e.get("event_type") == "created" for e in assignment_events_by_id.get(aid, [])):
                findings.append(_finding("plan_assignment_created_event_missing", "critical", assignment_id=aid))

        for oid, order in orders_by_id.items():
            item, outbox = purchases.get(oid), outbox_by_order.get(oid)
            if order.get("status") == "succeeded":
                if item is None:
                    findings.append(_finding("settled_payment_purchase_snapshot_missing", "critical", payment_order_id=oid))
                if outbox is None:
                    findings.append(_finding("settled_payment_fulfillment_missing", "critical", payment_order_id=oid))
                if not any(e.get("event_type") == "payment.succeeded" and e.get("processing_status") == "processed" for e in provider_events_by_order.get(oid, [])):
                    findings.append(_finding("settled_payment_provider_success_missing", "critical", payment_order_id=oid))
            elif outbox is not None:
                findings.append(_finding("unsettled_payment_has_fulfillment", "critical", payment_order_id=oid))
            if order.get("status") in {"refunded", "partially_refunded"}:
                findings.append(_finding("refund_lifecycle_not_implemented", "warning", payment_order_id=oid))
            events = order_events_by_order.get(oid, [])
            if events:
                try:
                    latest = max(events, key=lambda e: (_timestamp(e["occurred_at"]), str(e["id"])))
                    if latest.get("new_status") != order.get("status"):
                        findings.append(_finding("payment_order_event_projection_mismatch", "critical", payment_order_id=oid))
                except (KeyError, ValueError, TypeError):
                    findings.append(_finding("invalid_payment_order_event", "critical", payment_order_id=oid))
            else:
                findings.append(_finding("payment_order_event_history_missing", "warning", payment_order_id=oid))
            if outbox and outbox.get("status") == "completed" and item:
                entitlement_ref = "payment-order:" + oid
                if item.get("item_type") == "credit_pack":
                    matching_lots = [
                        lot for lot in credit_lots
                        if lot.get("user_id") == order.get("user_id")
                        and lot.get("idempotency_key") == entitlement_ref
                        and lot.get("source_reference") == entitlement_ref
                        and lot.get("granted_credits") == item.get("credit_quantity")
                    ]
                    if len(matching_lots) != 1:
                        findings.append(_finding("completed_credit_fulfillment_lot_mismatch", "critical", payment_order_id=oid))
                elif item.get("item_type") == "subscription":
                    assignment = assignment_by_order.get(oid)
                    if assignment is None or assignment.get("approved_plan_version_id") != item.get("approved_plan_version_id"):
                        findings.append(_finding("completed_subscription_fulfillment_assignment_missing", "critical", payment_order_id=oid))

        # Plan quota reservations must have a matching owner-scoped assignment,
        # request job, append-only reserved event and exactly one terminal event.
        reservations_by_id: dict[str, dict[str, Any]] = {}
        quota_event_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in quota_events:
            if not isinstance(event, dict) or not isinstance(event.get("reservation_id"), str):
                findings.append(_finding("invalid_plan_quota_event", "critical"))
                continue
            quota_event_map[event["reservation_id"]].append(event)
        usage: dict[tuple[str, str, str], int] = defaultdict(int)
        for reservation in quota_reservations:
            if not isinstance(reservation, dict):
                findings.append(_finding("invalid_plan_quota_reservation", "critical"))
                continue
            rid, owner, aid = reservation.get("id"), reservation.get("user_id"), reservation.get("assignment_id")
            operation_key, feature, state = reservation.get("operation_key"), reservation.get("feature_key"), reservation.get("status")
            if not isinstance(rid, str) or not rid or rid in reservations_by_id:
                findings.append(_finding("duplicate_or_invalid_plan_quota_reservation", "critical"))
                continue
            reservations_by_id[rid] = reservation
            assignment = assignment_by_id.get(aid)
            job = job_map.get(reservation.get("request_id"))
            if assignment is None or assignment.get("user_id") != owner:
                findings.append(_finding("plan_quota_assignment_mismatch", "critical", reservation_id=rid))
                continue
            if job is None or job.get("user_id") != owner:
                findings.append(_finding("plan_quota_request_job_mismatch", "critical", reservation_id=rid))
            if state not in {"reserved", "completed", "released"} or not isinstance(operation_key, str) or not operation_key:
                findings.append(_finding("invalid_plan_quota_reservation_state", "critical", reservation_id=rid))
                continue
            events = quota_event_map.get(rid, [])
            reserved_events = [e for e in events if e.get("event_type") == "reserved"]
            terminal_events = [e for e in events if e.get("event_type") in {"completed", "released"}]
            digest = md5(operation_key.encode("utf-8")).hexdigest()
            if len(reserved_events) != 1 or reserved_events[0].get("event_key") != "reserved:" + digest:
                findings.append(_finding("plan_quota_reserved_event_mismatch", "critical", reservation_id=rid))
            if state == "reserved":
                if terminal_events:
                    findings.append(_finding("plan_quota_terminal_event_mismatch", "critical", reservation_id=rid))
            elif len(terminal_events) != 1 or terminal_events[0].get("event_type") != state or terminal_events[0].get("event_key") != state + ":" + digest:
                findings.append(_finding("plan_quota_terminal_event_mismatch", "critical", reservation_id=rid))
            if job:
                job_status = job.get("status")
                concurrency = feature in {"max_concurrent_ai_requests", "max_parallel_jobs"}
                expected = ("released" if concurrency else "completed") if job_status == "succeeded" else "released" if job_status in {"failed", "cancelled", "expired"} else "reserved"
                if state != expected:
                    findings.append(_finding("plan_quota_job_lifecycle_mismatch", "critical", reservation_id=rid))
            plan = plan_by_id.get(assignment.get("approved_plan_version_id"))
            limits = plan.get("limits_json") if isinstance(plan, dict) else None
            raw_limit = limits.get(feature) if isinstance(limits, dict) else None
            if isinstance(raw_limit, str) and raw_limit.isdigit():
                limit = int(raw_limit)
            elif _integer(raw_limit):
                limit = raw_limit
            else:
                findings.append(_finding("plan_quota_limit_snapshot_missing", "critical", reservation_id=rid))
                continue
            period = reservation.get("period_start")
            if not isinstance(period, str):
                findings.append(_finding("invalid_plan_quota_period", "critical", reservation_id=rid))
                continue
            included = state in {"reserved", "completed"} and (feature not in {"max_concurrent_ai_requests", "max_parallel_jobs"} or state == "reserved")
            if included:
                usage[(owner, feature, period)] += reservation.get("reserved_units", 0)
            if not _integer(reservation.get("reserved_units")) or reservation["reserved_units"] <= 0:
                findings.append(_finding("invalid_plan_quota_units", "critical", reservation_id=rid))
            elif included and usage[(owner, feature, period)] > limit:
                findings.append(_finding("plan_quota_limit_exceeded", "critical", reservation_id=rid))
        for rid, events in quota_event_map.items():
            if rid not in reservations_by_id:
                findings.append(_finding("orphan_plan_quota_event", "critical"))
            if len({e.get("event_key") for e in events}) != len(events):
                findings.append(_finding("duplicate_plan_quota_event", "critical", reservation_id=rid))

    if not complete:
        findings.append(_finding("source_snapshot_incomplete", "warning"))
    if any(item["severity"] == "critical" for item in findings):
        status = "critical"
    elif not complete:
        status = "incomplete"
    elif findings:
        status = "warning"
    else:
        status = "healthy"

    counts = {
        "critical": sum(item["severity"] == "critical" for item in findings),
        "warning": sum(item["severity"] == "warning" for item in findings),
    }
    return {
        "status": status,
        "complete": complete,
        "counts": counts,
        "checked": {
            "ledger_entries": len(ledger_entries),
            "wallets": len(wallets),
            "generation_jobs": len(generation_jobs),
            "provider_cost_events": len(provider_cost_events),
            "credit_holds": len(credit_holds),
            "credit_lots": len(credit_lots),
            "hold_allocations": len(hold_allocations),
            "payment_orders": len(payment_orders),
            "payment_provider_events": len(payment_provider_events),
            "payment_order_events": len(payment_order_events),
            "purchase_items": len(purchase_items),
            "fulfillment_outbox": len(fulfillment_outbox),
            "plan_assignments": len(plan_assignments),
            "plan_assignment_events": len(plan_assignment_events),
            "approved_plans": len(approved_plans),
            "quota_reservations": len(quota_reservations),
            "quota_events": len(quota_events),
        },
        "findings": findings,
    }
