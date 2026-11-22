"""Read-only, keyset-paginated administrator credit ledger access."""
from datetime import datetime
from typing import Any
from uuid import UUID
import httpx
from app.core.config import Settings

class AdminCreditLedgerUnavailable(RuntimeError):
    pass

def list_admin_credit_ledger(settings: Settings, *, user_id: UUID,
    before_created_at: datetime | None = None, before_id: int | None = None,
    limit: int = 50) -> list[dict[str, Any]]:
    if not isinstance(user_id, UUID) or not 1 <= limit <= 100:
        raise ValueError("Invalid ledger query.")
    if (before_created_at is None) != (before_id is None):
        raise ValueError("Both cursor values are required.")
    if before_id is not None and (isinstance(before_id, bool) or before_id < 1):
        raise ValueError("Invalid ledger cursor.")
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise AdminCreditLedgerUnavailable("Admin credit ledger is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    payload = {"p_user_id": str(user_id),
        "p_before_created_at": before_created_at.isoformat() if before_created_at else None,
        "p_before_id": before_id, "p_limit": limit}
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/list_admin_credit_ledger",
                json=payload, headers=headers)
            response.raise_for_status()
            rows = response.json()
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError("invalid_page")
        safe = []
        allowed = {"grant", "reserve", "capture", "release", "refund", "adjustment"}
        for row in rows:
            if not isinstance(row, dict) or row.get("user_id") != str(user_id):
                raise ValueError("invalid_identity")
            if row.get("operation_type") not in allowed:
                raise ValueError("invalid_operation")
            if isinstance(row.get("entry_id"), bool) or not isinstance(row.get("entry_id"), int) or row["entry_id"] < 1:
                raise ValueError("invalid_entry_id")
            for field in ("delta_available", "delta_reserved", "balance_available_after", "balance_reserved_after"):
                if isinstance(row.get(field), bool) or not isinstance(row.get(field), int):
                    raise ValueError("invalid_amount")
            created = datetime.fromisoformat(str(row.get("created_at", "")).replace("Z", "+00:00"))
            if created.tzinfo is None:
                raise ValueError("invalid_timestamp")
            safe.append({"entry_id": row["entry_id"], "user_id": str(user_id),
                "hold_id": str(row["hold_id"]) if row.get("hold_id") else None,
                "operation_type": row["operation_type"], "delta_available": row["delta_available"],
                "delta_reserved": row["delta_reserved"], "balance_available_after": row["balance_available_after"],
                "balance_reserved_after": row["balance_reserved_after"], "created_at": created.isoformat()})
        return safe
    except Exception as exc:
        if isinstance(exc, AdminCreditLedgerUnavailable):
            raise
        raise AdminCreditLedgerUnavailable("Admin credit ledger is temporarily unavailable.") from exc
