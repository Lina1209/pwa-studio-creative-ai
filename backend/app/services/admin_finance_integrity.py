"""Read-only, single-snapshot administrator finance integrity audit."""
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.services.finance_integrity_audit import audit_finance_integrity


SNAPSHOT_LIMITS = {
    "ledger": 10000,
    "holds": 5000,
    "lots": 5000,
    "allocations": 10000,
    "jobs": 10000,
    "provider_cost_events": 10000,
    "payment_orders": 10000,
    "payment_provider_events": 20000,
    "payment_order_events": 20000,
    "purchase_items": 10000,
    "fulfillment_outbox": 10000,
    "plan_assignments": 10000,
    "plan_assignment_events": 20000,
    "approved_plans": 10000,
    "quota_reservations": 20000,
    "quota_events": 40000,
}


class FinanceIntegrityAuditError(RuntimeError):
    pass


class FinanceIntegrityAuditNotConfigured(FinanceIntegrityAuditError):
    pass


def _validate_snapshot(raw: Any, user_id: UUID) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("user_id") != str(user_id):
        raise ValueError("invalid_snapshot_identity")
    arrays = {
        "ledger": "ledger",
        "holds": "credit_holds",
        "lots": "credit_lots",
        "allocations": "hold_allocations",
        "jobs": "generation_jobs",
        "provider_cost_events": "provider_cost_events",
        "payment_orders": "payment_orders",
        "payment_provider_events": "payment_provider_events",
        "payment_order_events": "payment_order_events",
        "purchase_items": "purchase_items",
        "fulfillment_outbox": "fulfillment_outbox",
        "plan_assignments": "plan_assignments",
        "plan_assignment_events": "plan_assignment_events",
        "approved_plans": "approved_plans",
        "quota_reservations": "quota_reservations",
        "quota_events": "quota_events",
    }
    counts, limits = raw.get("counts"), raw.get("limits")
    if not isinstance(counts, dict) or not isinstance(limits, dict):
        raise ValueError("invalid_snapshot_bounds")
    validated: dict[str, list[dict[str, Any]]] = {}
    complete = raw.get("complete")
    if not isinstance(complete, bool):
        raise ValueError("invalid_snapshot_completeness")
    for source, key in arrays.items():
        rows = raw.get(source)
        count, limit = counts.get(source), limits.get(source)
        if (
            not isinstance(rows, list)
            or isinstance(count, bool) or not isinstance(count, int) or count < 0
            or limit != SNAPSHOT_LIMITS[source]
            or len(rows) > limit + 1
            or count < len(rows)
        ):
            raise ValueError("invalid_snapshot_source")
        if count != len(rows) or count > limit or len(rows) > limit:
            complete = False
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid_snapshot_row")
        # SQL deliberately returns one sentinel row beyond the cap. Never pass
        # that row into reconciliation; its presence only proves truncation.
        validated[key] = rows[:limit]
    expected_complete = all(counts[name] <= SNAPSHOT_LIMITS[name] for name in SNAPSHOT_LIMITS)
    if complete and not expected_complete:
        raise ValueError("snapshot_claims_false_completeness")
    validated["complete"] = complete and expected_complete
    wallet = raw.get("wallet")
    if not isinstance(wallet, dict):
        raise ValueError("invalid_wallet_snapshot")
    validated["wallet"] = wallet
    return validated


def get_finance_integrity_audit(settings: Settings, *, user_id: UUID) -> dict[str, Any]:
    if not isinstance(user_id, UUID):
        raise ValueError("invalid_user_id")
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise FinanceIntegrityAuditNotConfigured(
            "Finance integrity audit is not configured."
        )
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/get_finance_integrity_audit_snapshot",
                json={"p_user_id": str(user_id)},
                headers=headers,
            )
            response.raise_for_status()
            raw = response.json()
        snapshot = _validate_snapshot(raw, user_id)
        wallet = snapshot["wallet"]
        wallets = {str(user_id): wallet}
        report = audit_finance_integrity(
            ledger_entries=snapshot["ledger"],
            wallets=wallets,
            generation_jobs=snapshot["generation_jobs"],
            provider_cost_events=snapshot["provider_cost_events"],
            credit_holds=snapshot["credit_holds"],
            credit_lots=snapshot["credit_lots"],
            hold_allocations=snapshot["hold_allocations"],
            payment_orders=snapshot["payment_orders"],
            payment_provider_events=snapshot["payment_provider_events"],
            payment_order_events=snapshot["payment_order_events"],
            purchase_items=snapshot["purchase_items"],
            fulfillment_outbox=snapshot["fulfillment_outbox"],
            plan_assignments=snapshot["plan_assignments"],
            plan_assignment_events=snapshot["plan_assignment_events"],
            approved_plans=snapshot["approved_plans"],
            quota_reservations=snapshot["quota_reservations"],
            quota_events=snapshot["quota_events"],
            complete=snapshot["complete"],
        )
        if not wallet:
            report["findings"].append({
                "code": "wallet_row_missing",
                "severity": "warning",
                "user_id": str(user_id),
            })
            report["counts"]["warning"] += 1
            if report["status"] == "healthy":
                report["status"] = "warning"
        report["checked"]["snapshot_source"] = "single_postgresql_statement"
        report["checked"]["source_counts"] = {
            name: counts for name, counts in raw["counts"].items()
        }
        report["limits"] = dict(raw["limits"])
        return {
            "user_id": str(user_id),
            "status": report["status"],
            "complete": report["complete"],
            "counts": report["counts"],
            "checked": report["checked"],
            "limits": report["limits"],
            "findings": report["findings"],
            "read_only": True,
            "snapshot_consistency": "single_statement",
        }
    except FinanceIntegrityAuditError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        raise FinanceIntegrityAuditError(
            "Finance integrity audit could not load a complete, valid snapshot."
        ) from exc
