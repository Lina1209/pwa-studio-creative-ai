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
    if requester_id == target_user_id:
        raise ValueError("Finance requests must target a different user from the requester.")
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
    if scope_key != f"user:{target_user_id}":
        raise ValueError("Finance request scope must match its target user.")
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



def list_finance_operation_requests(
    settings: Settings, *, credit_scope_keys: list[str], billing_scope_keys: list[str],
    status: str | None, before: object | None, before_id: UUID | None, limit: int,
) -> list[dict]:
    from datetime import datetime

    if not isinstance(credit_scope_keys, list) or not isinstance(billing_scope_keys, list):
        raise ValueError("Finance scopes must be explicit lists.")
    if len(credit_scope_keys) > 100 or len(billing_scope_keys) > 100:
        raise ValueError("Too many finance scopes.")
    for scope in credit_scope_keys + billing_scope_keys:
        if not isinstance(scope, str) or not scope.startswith("user:") or len(scope) != 41:
            raise ValueError("Finance scope is invalid.")
        UUID(scope[5:])
    if status is not None and status not in {"pending", "approved", "rejected", "cancelled"}:
        raise ValueError("Finance request status is invalid.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 101:
        raise ValueError("Finance request page size is invalid.")
    if (before is None) != (before_id is None):
        raise ValueError("Both finance queue cursor fields are required.")
    if before is not None and (
        not isinstance(before, datetime) or before.tzinfo is None
        or not isinstance(before_id, UUID)
    ):
        raise ValueError("Finance queue cursor must be timezone-aware and complete.")

    result = _rpc(settings, "list_finance_operation_requests", {
        "p_credit_scope_keys": credit_scope_keys,
        "p_billing_scope_keys": billing_scope_keys,
        "p_status": status,
        "p_before": before.isoformat() if before is not None else None,
        "p_before_id": str(before_id) if before_id is not None else None,
        "p_limit": limit,
    })
    if not isinstance(result, list) or len(result) > limit:
        raise FinanceRequestUnavailable("Finance request queue returned an invalid page.")

    parsed_rows: list[dict] = []
    for row in result:
        if not isinstance(row, dict):
            raise FinanceRequestUnavailable("Finance request queue returned malformed data.")
        try:
            item = {
                "request_id": UUID(str(row["request_id"])),
                "requester_id": UUID(str(row["requester_id"])),
                "request_type": str(row["request_type"]),
                "target_user_id": UUID(str(row["target_user_id"])),
                "amount": Decimal(str(row["amount"])),
                "currency_code": str(row["currency_code"]),
                "scope_key": str(row["scope_key"]),
                "reason": str(row["reason"]),
                "status": str(row["status"]),
                "requested_at": datetime.fromisoformat(str(row["requested_at"]).replace("Z", "+00:00")),
                "decided_by": UUID(str(row["decided_by"])) if row.get("decided_by") else None,
                "decided_at": datetime.fromisoformat(str(row["decided_at"]).replace("Z", "+00:00")) if row.get("decided_at") else None,
                "decision_reason": str(row["decision_reason"]) if row.get("decision_reason") is not None else None,
                "cancelled_at": datetime.fromisoformat(str(row["cancelled_at"]).replace("Z", "+00:00")) if row.get("cancelled_at") else None,
            }
            if item["request_type"] not in REQUEST_TYPES or item["status"] not in {
                "pending", "approved", "rejected", "cancelled"
            }:
                raise ValueError("unknown request type or status")
            if not item["amount"].is_finite() or item["amount"] <= 0:
                raise ValueError("invalid amount")
            if item["requested_at"].tzinfo is None or item["scope_key"] != f"user:{item['target_user_id']}":
                raise ValueError("invalid scope or timestamp")
            if item["request_type"] == "credit_compensation":
                if item["currency_code"] != "CRD" or item["amount"] != item["amount"].to_integral_value():
                    raise ValueError("invalid credit units")
            elif item["currency_code"] == "CRD":
                raise ValueError("invalid refund currency")
            parsed_rows.append(item)
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            raise FinanceRequestUnavailable("Finance request queue returned malformed data.") from exc
    return parsed_rows
