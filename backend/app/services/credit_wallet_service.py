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


def _nonnegative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CreditWalletUnavailable(f"Credit wallet returned invalid {field}.")
    return value


def get_credit_wallet_snapshot(
    settings: Settings, *, user_id: UUID, history_limit: int = 50
) -> CreditWalletSnapshot:
    if not 1 <= history_limit <= 100:
        raise ValueError("Credit history limit must be between 1 and 100.")
    headers = _headers(settings)
    base = settings.supabase_url.rstrip("/")
    try:
        with httpx.Client(timeout=8.0) as client:
            wallet_response = client.get(
                f"{base}/rest/v1/credit_wallets",
                params={
                    "select": "available_credits,reserved_credits,currency_unit",
                    "user_id": f"eq.{user_id}",
                    "limit": "2",
                },
                headers=headers,
            )
            wallet_response.raise_for_status()
            wallets = wallet_response.json()
            if not isinstance(wallets, list) or len(wallets) > 1:
                raise CreditWalletUnavailable("Credit wallet returned an ambiguous response.")

            holds_response = client.get(
                f"{base}/rest/v1/credit_holds",
                params={
                    "select": "id,job_id,amount,status,created_at",
                    "user_id": f"eq.{user_id}",
                    "status": "eq.held",
                    "order": "created_at.desc",
                    "limit": "20",
                },
                headers=headers,
            )
            holds_response.raise_for_status()
            holds = holds_response.json()

            ledger_response = client.get(
                f"{base}/rest/v1/credit_ledger",
                params={
                    "select": "id,operation_type,operation_key,delta_available,delta_reserved,balance_available_after,balance_reserved_after,created_at",
                    "user_id": f"eq.{user_id}",
                    "order": "created_at.desc,id.desc",
                    "limit": str(history_limit),
                },
                headers=headers,
            )
            ledger_response.raise_for_status()
            ledger = ledger_response.json()
    except CreditWalletNotConfigured:
        raise
    except CreditWalletUnavailable:
        raise
    except Exception as exc:
        raise CreditWalletUnavailable("Credit wallet data is temporarily unavailable.") from exc

    if not isinstance(holds, list) or not isinstance(ledger, list):
        raise CreditWalletUnavailable("Credit wallet history returned an invalid response.")

    if wallets:
        wallet = wallets[0]
        if not isinstance(wallet, dict) or wallet.get("currency_unit") != "credit":
            raise CreditWalletUnavailable("Credit wallet metadata is invalid.")
        available = _nonnegative_integer(wallet.get("available_credits"), "available balance")
        reserved = _nonnegative_integer(wallet.get("reserved_credits"), "reserved balance")
    else:
        available, reserved = 0, 0

    safe_holds: list[dict[str, Any]] = []
    for hold in holds:
        if not isinstance(hold, dict) or hold.get("status") != "held":
            raise CreditWalletUnavailable("Credit hold history is invalid.")
        safe_holds.append({
            "id": str(hold.get("id", "")),
            "job_id": str(hold.get("job_id", "")),
            "amount": _nonnegative_integer(hold.get("amount"), "held amount"),
            "status": "held",
            "created_at": hold.get("created_at"),
        })

    safe_ledger: list[dict[str, Any]] = []
    for entry in ledger:
        if not isinstance(entry, dict):
            raise CreditWalletUnavailable("Credit ledger history is invalid.")
        safe_ledger.append({
            "id": _nonnegative_integer(entry.get("id"), "ledger id"),
            "operation_type": entry.get("operation_type"),
            "operation_key": entry.get("operation_key"),
            "delta_available": entry.get("delta_available"),
            "delta_reserved": entry.get("delta_reserved"),
            "balance_available_after": _nonnegative_integer(
                entry.get("balance_available_after"), "ledger available balance"
            ),
            "balance_reserved_after": _nonnegative_integer(
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
