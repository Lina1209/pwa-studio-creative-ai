"""Pure, read-only finance integrity checks over explicitly supplied snapshots.

The module does not fetch data, mutate balances, or repair financial records.
Callers must only mark an audit complete when every source has been fully paginated.
"""
from collections import defaultdict
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
    credit_holds = [] if credit_holds is None else credit_holds
    credit_lots = [] if credit_lots is None else credit_lots
    hold_allocations = [] if hold_allocations is None else hold_allocations
    if not all(isinstance(rows, list) for rows in (credit_holds, credit_lots, hold_allocations)):
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
        },
        "findings": findings,
    }
