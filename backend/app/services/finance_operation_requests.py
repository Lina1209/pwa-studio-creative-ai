"""Server-only finance operation request RPC client.

This module creates and transitions request records only. It never executes
credit ledger mutations or contacts payment providers.
"""
from decimal import Decimal, InvalidOperation
from uuid import UUID

import httpx

from app.core.config import Settings


class FinanceRequestNotConfigured(RuntimeError):
    pass


class FinanceRequestUnavailable(RuntimeError):
    pass


class FinanceRequestConflict(RuntimeError):
    pass


class FinanceRequestNotFound(RuntimeError):
    pass


REQUEST_TYPES = frozenset({"credit_compensation", "billing_refund"})
DECISIONS = frozenset({"approve", "reject"})


def _rpc(settings: Settings, name: str, payload: dict):
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise FinanceRequestNotConfigured("Finance request storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
                json=payload,
                headers=headers,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                error_code = None
                try:
                    error_code = exc.response.json().get("code")
                except Exception:
                    pass
                if exc.response.status_code == 409 or error_code in {"55000", "23505"}:
                    raise FinanceRequestConflict("Finance request conflicts with its current state.") from exc
                if error_code == "P0002":
                    raise FinanceRequestNotFound("Finance request was not found.") from exc
                if error_code == "22023":
                    raise ValueError("Finance request parameters or transition are invalid.") from exc
                raise
            return response.json()
    except (FinanceRequestNotConfigured, FinanceRequestConflict, FinanceRequestNotFound, ValueError):
        raise
    except Exception as exc:
        raise FinanceRequestUnavailable("Finance request storage is temporarily unavailable.") from exc


def create_finance_operation_request(
    settings: Settings, *, requester_id: UUID, request_type: str,
    target_user_id: UUID, amount: Decimal, currency_code: str,
    scope_key: str, reason: str, idempotency_key: UUID,
) -> UUID:
    if not isinstance(requester_id, UUID) or not isinstance(target_user_id, UUID):
        raise ValueError("Verified requester and target UUIDs are required.")
    if request_type not in REQUEST_TYPES:
        raise ValueError("Unsupported finance request type.")
    try:
        normalized_amount = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Finance request amount is invalid.") from exc
    if not normalized_amount.is_finite() or normalized_amount <= 0 or normalized_amount.as_tuple().exponent < -4:
        raise ValueError("Finance request amount must be positive with at most four decimal places.")
    if not isinstance(currency_code, str) or len(currency_code) != 3 or not currency_code.isascii() or not currency_code.isalpha() or currency_code != currency_code.upper():
        raise ValueError("Currency must be a three-letter uppercase code.")
    if request_type == "credit_compensation":
        if currency_code != "CRD" or normalized_amount != normalized_amount.to_integral_value():
            raise ValueError("Credit compensation must use whole credits and the CRD unit.")
    elif currency_code == "CRD":
        raise ValueError("Cash refunds must use a currency code, not the CRD credit unit.")
    if not isinstance(scope_key, str) or not 1 <= len(scope_key) <= 200 or scope_key.strip() != scope_key:
        raise ValueError("An explicit finance request scope is required.")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 500 or reason.strip() != reason:
        raise ValueError("A trimmed reason of 1 to 500 characters is required.")
    if not isinstance(idempotency_key, UUID):
        raise ValueError("A UUID idempotency key is required.")
    result = _rpc(settings, "create_finance_operation_request", {
        "p_requester_id": str(requester_id),
        "p_request_type": request_type,
        "p_target_user_id": str(target_user_id),
        "p_amount": format(normalized_amount, "f"),
        "p_currency_code": currency_code,
        "p_scope_key": scope_key,
        "p_reason": reason,
        "p_idempotency_key": str(idempotency_key),
    })
    try:
        return UUID(str(result))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinanceRequestUnavailable("Finance request RPC returned an invalid identifier.") from exc


def decide_finance_operation_request(
    settings: Settings, *, request_id: UUID, actor_id: UUID,
    decision: str, reason: str,
) -> UUID:
    if not isinstance(request_id, UUID) or not isinstance(actor_id, UUID):
        raise ValueError("Request and verified actor UUIDs are required.")
    if decision not in DECISIONS:
        raise ValueError("Unsupported finance request decision.")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 500 or reason.strip() != reason:
        raise ValueError("A trimmed decision reason is required.")
    result = _rpc(settings, "decide_finance_operation_request", {
        "p_request_id": str(request_id), "p_actor_id": str(actor_id),
        "p_decision": decision, "p_reason": reason,
    })
    try:
        returned = UUID(str(result))
        if returned != request_id:
            raise ValueError("mismatched request id")
        return returned
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinanceRequestUnavailable("Finance decision RPC returned an invalid identifier.") from exc


def cancel_finance_operation_request(
    settings: Settings, *, request_id: UUID, actor_id: UUID, reason: str,
) -> UUID:
    if not isinstance(request_id, UUID) or not isinstance(actor_id, UUID):
        raise ValueError("Request and verified actor UUIDs are required.")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 500 or reason.strip() != reason:
        raise ValueError("A trimmed cancellation reason is required.")
    result = _rpc(settings, "cancel_finance_operation_request", {
        "p_request_id": str(request_id), "p_actor_id": str(actor_id),
        "p_reason": reason,
    })
    try:
        returned = UUID(str(result))
        if returned != request_id:
            raise ValueError("mismatched request id")
        return returned
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinanceRequestUnavailable("Finance cancellation RPC returned an invalid identifier.") from exc


def read_finance_operation_request(settings: Settings, *, request_id: UUID) -> dict:
    if not isinstance(request_id, UUID):
        raise ValueError("Finance request UUID is required.")
    result = _rpc(settings, "read_finance_operation_request", {"p_request_id": str(request_id)})
    if result == []:
        raise FinanceRequestNotFound("Finance request was not found.")
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise FinanceRequestUnavailable("Finance request lookup returned an invalid result.")
    row = result[0]
    try:
        parsed = {
            "request_id": UUID(str(row["request_id"])),
            "requester_id": UUID(str(row["requester_id"])),
            "request_type": str(row["request_type"]),
            "target_user_id": UUID(str(row["target_user_id"])),
            "amount": Decimal(str(row["amount"])),
            "currency_code": str(row["currency_code"]),
            "scope_key": str(row["scope_key"]),
            "status": str(row["status"]),
        }
        if parsed["request_type"] not in REQUEST_TYPES or parsed["status"] not in {
            "pending", "approved", "rejected", "cancelled"
        }:
            raise ValueError("unknown request type or state")
        if parsed["request_id"] != request_id or not parsed["scope_key"]:
            raise ValueError("mismatched request record")
        return parsed
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        raise FinanceRequestUnavailable("Finance request lookup returned malformed data.") from exc
