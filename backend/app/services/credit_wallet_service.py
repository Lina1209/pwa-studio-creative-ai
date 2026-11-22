"""Read-only, owner-scoped credit wallet projection and history."""
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class CreditWalletNotConfigured(RuntimeError):
    pass


class CreditWalletUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CreditWalletSnapshot:
    user_id: UUID
    available_credits: int
    reserved_credits: int
    holds: list[dict[str, Any]]
    ledger: list[dict[str, Any]]


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise CreditWalletNotConfigured("Credit wallet storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CreditWalletUnavailable(f"Credit wallet returned invalid {field}.")
    return value


def get_credit_wallet_snapshot(
    settings: Settings, *, user_id: UUID, history_limit: int = 50
) -> CreditWalletSnapshot:
    if not isinstance(user_id, UUID):
        raise ValueError("Verified user UUID is required.")
    if not 1 <= history_limit <= 100:
        raise ValueError("Credit history limit must be between 1 and 100.")
    headers = _headers(settings)
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/get_credit_wallet_snapshot"
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                url,
                json={"p_user_id": str(user_id), "p_history_limit": history_limit},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except CreditWalletNotConfigured:
        raise
    except Exception as exc:
        raise CreditWalletUnavailable("Credit wallet data is temporarily unavailable.") from exc

    if not isinstance(data, dict) or data.get("user_id") != str(user_id):
        raise CreditWalletUnavailable("Credit wallet snapshot identity is invalid.")
    if data.get("currency_unit") != "credit":
        raise CreditWalletUnavailable("Credit wallet currency metadata is invalid.")
    available = _integer(data.get("available_credits"), "available balance")
    reserved = _integer(data.get("reserved_credits"), "reserved balance")
    holds = data.get("holds")
    ledger = data.get("ledger")
    if not isinstance(holds, list) or len(holds) > 20:
        raise CreditWalletUnavailable("Credit hold history is invalid.")
    if not isinstance(ledger, list) or len(ledger) > history_limit:
        raise CreditWalletUnavailable("Credit ledger history is invalid.")

    safe_holds: list[dict[str, Any]] = []
    for hold in holds:
        if not isinstance(hold, dict) or hold.get("status") != "held":
            raise CreditWalletUnavailable("Credit hold history is invalid.")
        safe_holds.append({
            "id": str(hold.get("id", "")),
            "job_id": str(hold.get("job_id", "")),
            "amount": _integer(hold.get("amount"), "held amount", minimum=1),
            "status": "held",
            "created_at": hold.get("created_at"),
        })

    safe_ledger: list[dict[str, Any]] = []
    for entry in ledger:
        if not isinstance(entry, dict):
            raise CreditWalletUnavailable("Credit ledger history is invalid.")
        safe_ledger.append({
            "id": _integer(entry.get("id"), "ledger id", minimum=1),
            "operation_type": entry.get("operation_type"),
            "operation_key": entry.get("operation_key"),
            "delta_available": _integer_signed(entry.get("delta_available"), "available delta"),
            "delta_reserved": _integer_signed(entry.get("delta_reserved"), "reserved delta"),
            "balance_available_after": _integer(
                entry.get("balance_available_after"), "ledger available balance"
            ),
            "balance_reserved_after": _integer(
                entry.get("balance_reserved_after"), "ledger reserved balance"
            ),
            "created_at": entry.get("created_at"),
        })
    return CreditWalletSnapshot(
        user_id=user_id,
        available_credits=available,
        reserved_credits=reserved,
        holds=safe_holds,
        ledger=safe_ledger,
    )


def _integer_signed(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CreditWalletUnavailable(f"Credit wallet returned invalid {field}.")
    return value
