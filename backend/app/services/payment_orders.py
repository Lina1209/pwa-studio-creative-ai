"""Server-only payment order RPC client.

No public route calls this module yet. Provider adapters must verify the raw
webhook signature before calling record_verified_provider_event. This module
never grants credits and never treats browser redirects as payment evidence.
"""
import hashlib
import re
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class PaymentOrderNotConfigured(RuntimeError):
    pass


class PaymentOrderUnavailable(RuntimeError):
    pass


class PaymentOrderConflict(RuntimeError):
    pass


class PaymentOrderNotFound(RuntimeError):
    pass


_PROVIDER = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_EVENT_TYPES = frozenset({
    "payment.pending", "payment.succeeded", "payment.failed", "payment.cancelled",
})


def _rpc(settings: Settings, name: str, payload: dict[str, Any]):
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise PaymentOrderNotConfigured("Payment order storage is not configured.")
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
                code = None
                try:
                    code = exc.response.json().get("code")
                except Exception:
                    pass
                if exc.response.status_code == 409 or code in {"23505", "23514", "55000"}:
                    raise PaymentOrderConflict("Payment order conflicts with its current state.") from exc
                if code == "P0002":
                    raise PaymentOrderNotFound("Payment order was not found.") from exc
                if code == "22023":
                    raise ValueError("Payment order parameters are invalid.") from exc
                raise
            return response.json()
    except (PaymentOrderNotConfigured, PaymentOrderConflict, PaymentOrderNotFound, ValueError):
        raise
    except Exception as exc:
        raise PaymentOrderUnavailable("Payment order storage is temporarily unavailable.") from exc


def _one_row(result: Any, *, name: str) -> dict:
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise PaymentOrderUnavailable(f"{name} RPC returned an invalid result.")
    return result[0]


def create_payment_order(
    settings: Settings, *, user_id: UUID, provider_code: str,
    merchant_reference: str, idempotency_key: UUID, amount_minor: int,
    currency_code: str, description: str, metadata: dict | None = None,
) -> dict:
    """Create an order from server-calculated pricing; never accept browser price data."""
    if not isinstance(user_id, UUID) or not isinstance(idempotency_key, UUID):
        raise ValueError("Verified user and idempotency UUIDs are required.")
    if not isinstance(provider_code, str) or not _PROVIDER.fullmatch(provider_code):
        raise ValueError("Payment provider code is invalid.")
    if not isinstance(merchant_reference, str) or not 8 <= len(merchant_reference) <= 120:
        raise ValueError("Merchant reference is invalid.")
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or not 1 <= amount_minor <= 1_000_000_000_000_000:
        raise ValueError("Payment amount must be a positive integer in minor units.")
    if not isinstance(currency_code, str) or not _CURRENCY.fullmatch(currency_code):
        raise ValueError("Currency code must be three uppercase letters.")
    if not isinstance(description, str) or not 1 <= len(description) <= 240 or description.strip() != description:
        raise ValueError("Payment description is invalid.")
    safe_metadata = {} if metadata is None else metadata
    if not isinstance(safe_metadata, dict) or len(str(safe_metadata).encode("utf-8")) > 4096:
        raise ValueError("Payment metadata must be a small object.")
    row = _one_row(_rpc(settings, "create_payment_order", {
        "p_user_id": str(user_id), "p_provider_code": provider_code,
        "p_merchant_reference": merchant_reference,
        "p_idempotency_key": str(idempotency_key),
        "p_amount_minor": amount_minor, "p_currency_code": currency_code,
        "p_description": description, "p_metadata": safe_metadata,
    }), name="create_payment_order")
    try:
        order_id = UUID(str(row["payment_order_id"]))
        replayed = row["replayed"]
        if not isinstance(replayed, bool):
            raise ValueError("invalid replay flag")
        return {"payment_order_id": order_id, "replayed": replayed}
    except (KeyError, ValueError, TypeError) as exc:
        raise PaymentOrderUnavailable("Payment order RPC returned malformed data.") from exc



def _create_snapshot_purchase_order(
    settings: Settings, *, rpc_name: str, user_id: UUID, provider_code: str,
    merchant_reference: str, idempotency_key: UUID, approved_version_id: UUID,
    metadata: dict | None = None,
) -> dict:
    """Create a catalog-backed order; the database supplies authoritative price and currency."""
    if not isinstance(user_id, UUID) or not isinstance(idempotency_key, UUID):
        raise ValueError("Verified user and idempotency UUIDs are required.")
    if not isinstance(approved_version_id, UUID):
        raise ValueError("An approved immutable product version UUID is required.")
    if not isinstance(provider_code, str) or not _PROVIDER.fullmatch(provider_code):
        raise ValueError("Payment provider code is invalid.")
    if not isinstance(merchant_reference, str) or not 8 <= len(merchant_reference) <= 120:
        raise ValueError("Merchant reference is invalid.")
    safe_metadata = {} if metadata is None else metadata
    if not isinstance(safe_metadata, dict) or len(str(safe_metadata).encode("utf-8")) > 4096:
        raise ValueError("Payment metadata must be a small object.")
    row = _one_row(_rpc(settings, rpc_name, {
        "p_user_id": str(user_id),
        "p_provider_code": provider_code,
        "p_merchant_reference": merchant_reference,
        "p_idempotency_key": str(idempotency_key),
        "p_" + ("credit_pack_version_id" if rpc_name == "create_credit_pack_payment_order" else "approved_plan_version_id"): str(approved_version_id),
        "p_metadata": safe_metadata,
    }), name=rpc_name)
    try:
        order_id = UUID(str(row["payment_order_id"]))
        replayed = row["replayed"]
        if not isinstance(replayed, bool):
            raise ValueError("invalid replay flag")
        return {"payment_order_id": order_id, "replayed": replayed}
    except (KeyError, ValueError, TypeError) as exc:
        raise PaymentOrderUnavailable(f"{rpc_name} RPC returned malformed data.") from exc


def create_credit_pack_payment_order(
    settings: Settings, *, user_id: UUID, provider_code: str,
    merchant_reference: str, idempotency_key: UUID,
    credit_pack_version_id: UUID, metadata: dict | None = None,
) -> dict:
    return _create_snapshot_purchase_order(
        settings, rpc_name="create_credit_pack_payment_order", user_id=user_id,
        provider_code=provider_code, merchant_reference=merchant_reference,
        idempotency_key=idempotency_key, approved_version_id=credit_pack_version_id,
        metadata=metadata,
    )


def create_subscription_payment_order(
    settings: Settings, *, user_id: UUID, provider_code: str,
    merchant_reference: str, idempotency_key: UUID,
    approved_plan_version_id: UUID, metadata: dict | None = None,
) -> dict:
    return _create_snapshot_purchase_order(
        settings, rpc_name="create_subscription_payment_order", user_id=user_id,
        provider_code=provider_code, merchant_reference=merchant_reference,
        idempotency_key=idempotency_key, approved_version_id=approved_plan_version_id,
        metadata=metadata,
    )



def claim_payment_fulfillment(
    settings: Settings, *, lease_seconds: int = 120, batch_size: int = 1,
) -> list[dict]:
    """Claim a bounded batch using database-issued fencing tokens."""
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 15 <= lease_seconds <= 900:
        raise ValueError("Payment fulfillment lease must be between 15 and 900 seconds.")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 20:
        raise ValueError("Payment fulfillment batch size must be between 1 and 20.")
    result = _rpc(settings, "claim_payment_fulfillment", {
        "p_lease_seconds": lease_seconds, "p_batch_size": batch_size,
    })
    if not isinstance(result, list):
        raise PaymentOrderUnavailable("claim_payment_fulfillment RPC returned an invalid result.")
    claimed = []
    try:
        for row in result:
            if not isinstance(row, dict):
                raise ValueError("invalid claim row")
            claimed.append({
                "fulfillment_id": UUID(str(row["fulfillment_id"])),
                "payment_order_id": UUID(str(row["payment_order_id"])),
                "user_id": UUID(str(row["user_id"])),
                "provider_code": str(row["provider_code"]),
                "amount_minor": int(row["amount_minor"]),
                "currency_code": str(row["currency_code"]),
                "attempt_count": int(row["attempt_count"]),
                "lease_token": UUID(str(row["lease_token"])),
                "lease_expires_at": str(row["lease_expires_at"]),
            })
    except (KeyError, ValueError, TypeError) as exc:
        raise PaymentOrderUnavailable("claim_payment_fulfillment RPC returned malformed data.") from exc
    return claimed


def fulfill_payment_order(
    settings: Settings, *, fulfillment_id: UUID, lease_token: UUID,
) -> dict:
    """Atomically create the purchase entitlement and complete its leased outbox item."""
    if not isinstance(fulfillment_id, UUID) or not isinstance(lease_token, UUID):
        raise ValueError("Fulfillment ID and database-issued lease token UUIDs are required.")
    row = _one_row(_rpc(settings, "fulfill_payment_order", {
        "p_fulfillment_id": str(fulfillment_id),
        "p_lease_token": str(lease_token),
    }), name="fulfill_payment_order")
    try:
        status = str(row["fulfillment_status"])
        purchase_type = str(row["purchase_type"])
        entitlement_reference = str(row["entitlement_reference"])
        replayed = row["replayed"]
        if status != "completed" or purchase_type not in {"credit_pack", "subscription"} or not isinstance(replayed, bool):
            raise ValueError("invalid fulfillment result")
        return {
            "fulfillment_status": status,
            "purchase_type": purchase_type,
            "entitlement_reference": entitlement_reference,
            "replayed": replayed,
        }
    except (KeyError, ValueError, TypeError) as exc:
        raise PaymentOrderUnavailable("fulfill_payment_order RPC returned malformed data.") from exc


def fail_payment_fulfillment(
    settings: Settings, *, fulfillment_id: UUID, lease_token: UUID,
    error_code: str, retry_after_seconds: int = 60,
) -> str:
    """Release a failed claim through the fenced retry RPC; never mutates outbox directly."""
    if not isinstance(fulfillment_id, UUID) or not isinstance(lease_token, UUID):
        raise ValueError("Fulfillment ID and lease token UUIDs are required.")
    if not isinstance(error_code, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,80}", error_code):
        raise ValueError("Payment fulfillment error code is invalid.")
    if isinstance(retry_after_seconds, bool) or not isinstance(retry_after_seconds, int) or not 0 <= retry_after_seconds <= 86400:
        raise ValueError("Payment fulfillment retry delay is invalid.")
    result = _rpc(settings, "fail_payment_fulfillment", {
        "p_fulfillment_id": str(fulfillment_id),
        "p_lease_token": str(lease_token),
        "p_error_code": error_code,
        "p_retry_after_seconds": retry_after_seconds,
        "p_max_attempts": 5,
    })
    if not isinstance(result, str) or result not in {"queued", "manual_review", "lease_lost"}:
        raise PaymentOrderUnavailable("fail_payment_fulfillment RPC returned an invalid result.")
    return result


def record_verified_provider_event(
    settings: Settings, *, provider_code: str, provider_event_id: str,
    payment_order_id: UUID, event_type: str, raw_body: bytes,
    signature_verified: bool, amount_minor: int, currency_code: str,
    provider_payment_id: str,
) -> dict:
    """Persist a normalized webhook event only after adapter-level signature verification."""
    if signature_verified is not True:
        raise ValueError("A provider signature must be verified before event ingestion.")
    if not isinstance(provider_code, str) or not _PROVIDER.fullmatch(provider_code):
        raise ValueError("Payment provider code is invalid.")
    if not isinstance(provider_event_id, str) or not 1 <= len(provider_event_id) <= 240:
        raise ValueError("Provider event identifier is invalid.")
    if not isinstance(payment_order_id, UUID):
        raise ValueError("Payment order UUID is required.")
    if event_type not in _EVENT_TYPES:
        raise ValueError("Unsupported normalized provider event type.")
    if not isinstance(raw_body, bytes) or not 1 <= len(raw_body) <= 1_000_000:
        raise ValueError("Raw webhook body is invalid.")
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
        raise ValueError("Verified provider amount is invalid.")
    if not isinstance(currency_code, str) or not _CURRENCY.fullmatch(currency_code):
        raise ValueError("Verified provider currency is invalid.")
    if not isinstance(provider_payment_id, str) or not 1 <= len(provider_payment_id) <= 240:
        raise ValueError("Provider payment identifier is invalid.")

    row = _one_row(_rpc(settings, "record_verified_payment_provider_event", {
        "p_provider_code": provider_code,
        "p_provider_event_id": provider_event_id,
        "p_payment_order_id": str(payment_order_id),
        "p_event_type": event_type,
        "p_payload_sha256": hashlib.sha256(raw_body).hexdigest(),
        "p_amount_minor": amount_minor,
        "p_currency_code": currency_code,
        "p_provider_payment_id": provider_payment_id,
    }), name="record_verified_payment_provider_event")
    try:
        event_id = UUID(str(row["event_id"]))
        replayed = row["replayed"]
        resulting_status = str(row["resulting_status"])
        if not isinstance(replayed, bool) or resulting_status not in {
            "created", "pending", "succeeded", "failed", "cancelled"
        }:
            raise ValueError("invalid event result")
        return {"event_id": event_id, "replayed": replayed, "resulting_status": resulting_status}
    except (KeyError, ValueError, TypeError) as exc:
        raise PaymentOrderUnavailable("Payment event RPC returned malformed data.") from exc
