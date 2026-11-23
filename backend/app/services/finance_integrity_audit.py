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
    opening_balances: dict[str, tuple[int, int]] | None = None,
    complete: bool = True,
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
    if not isinstance(complete, bool):
        raise ValueError("invalid_completeness_flag")

    findings: list[dict[str, Any]] = []
    ledger_by_user: dict[str, list[tuple[datetime, int, dict[str, Any]]]] = defaultdict(list)
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
            if raw["balance_available_after"] < 0 or raw["balance_reserved_after"] < 0:
                findings.append(_finding("negative_ledger_balance", "critical", user_id=user_id, entry_id=entry_id))
            created = _timestamp(raw.get("created_at"))
            ledger_by_user[user_id].append((created, entry_id, raw))
        except (ValueError, TypeError, AttributeError):
            findings.append(_finding("invalid_ledger_row", "critical"))

    opening_balances = opening_balances or {}
    for user_id, entries in ledger_by_user.items():
        # Identity IDs are allocated when the ledger insert occurs. Lifecycle RPCs\n        # serialize mutations on the wallet row, so ID order is the accounting order;\n        # created_at uses transaction-start time and can be misleading under concurrency.\n        entries.sort(key=lambda item: item[1])
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
        usage_id, source = event.get("provider_usage_id"), event.get("cost_source")
        if (
            not _integer(event_id) or event_id < 1
            or not isinstance(job_id, str) or job_id not in job_map
            or not isinstance(operation_key, str) or not operation_key
            or not isinstance(provider, str) or not provider
        ):
            findings.append(_finding("orphan_or_invalid_provider_cost_event", "critical"))
            continue
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

    if any(item["severity"] == "critical" for item in findings):
        status = "critical"
    elif not complete:
        status = "incomplete"
        findings.append(_finding("source_snapshot_incomplete", "warning"))
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
        },
        "findings": findings,
    }
