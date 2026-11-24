"""Trusted server-side adapter for the unified PWA Studio credit wallet.

This module is deliberately not wired to generation endpoints yet: callers must
resolve pricing on the server before reserving credits.
"""
import re
from uuid import UUID

import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.supabase_rest import supabase_headers
from app.services.pricing_service import (
    AI_PRICING_CATALOG, AIPricingRule, PricingError, PricingQuote,
    PricingSettlement, quote_ai_operation, settle_ai_operation,
)

_MAX_CREDITS = 100_000_000
_OPERATION_RE = re.compile(r"^[a-z0-9_.-]{1,80}$")
_GRANT_SOURCES = {"plan_cycle", "purchase", "promo", "admin_adjustment", "refund"}


def _validate_user_id(user_id: str) -> str:
    try:
        return str(UUID(user_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("user_id must be a valid UUID") from exc


def _validate_amount(amount: int, *, allow_zero: bool = False) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError("credit amount must be an integer")
    minimum = 0 if allow_zero else 1
    if amount < minimum or amount > _MAX_CREDITS:
        raise ValueError("credit amount is outside the allowed range")
    return amount


def _rpc(settings: Settings, function: str, payload: dict) -> dict:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Credit storage is not configured.")
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{function}"
    try:
        response = httpx.post(
            url,
            headers=supabase_headers(settings, prefer="return=representation"),
            json=payload,
            timeout=8.0,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            raise ValueError("Credit RPC returned an unexpected response.")
        return result
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Credit storage is temporarily unavailable.",
        ) from exc


def grant_credits(
    settings: Settings, *, user_id: str, amount: int, source: str, source_reference: str
) -> dict:
    """Grant credits only for a trusted, verified server-side event."""
    uid = _validate_user_id(user_id)
    _validate_amount(amount)
    if source not in _GRANT_SOURCES:
        raise ValueError("unsupported credit grant source")
    if not isinstance(source_reference, str) or not 1 <= len(source_reference) <= 160:
        raise ValueError("source_reference must contain 1 to 160 characters")
    return _rpc(settings, "grant_user_credits", {
        "p_user_id": uid,
        "p_amount": amount,
        "p_source": source,
        "p_source_reference": source_reference,
    })


def reserve_credits(
    settings: Settings, *, user_id: str, idempotency_key: str,
    operation_code: str, pricing_version: int, amount: int
) -> dict:
    uid = _validate_user_id(user_id)
    _validate_amount(amount)
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160:
        raise ValueError("idempotency_key must contain 8 to 160 characters")
    if not isinstance(operation_code, str) or not _OPERATION_RE.fullmatch(operation_code):
        raise ValueError("operation_code has an invalid format")
    if isinstance(pricing_version, bool) or not isinstance(pricing_version, int) or pricing_version < 1:
        raise ValueError("pricing_version must be a positive integer")
    return _rpc(settings, "reserve_user_credits", {
        "p_user_id": uid,
        "p_idempotency_key": idempotency_key,
        "p_operation_code": operation_code,
        "p_pricing_version": pricing_version,
        "p_amount": amount,
    })


def settle_reservation(
    settings: Settings, *, user_id: str, reservation_id: str, capture_amount: int
) -> dict:
    uid = _validate_user_id(user_id)
    _validate_amount(capture_amount, allow_zero=True)
    rid = str(UUID(reservation_id))
    return _rpc(settings, "settle_user_credit_reservation", {
        "p_user_id": uid,
        "p_reservation_id": rid,
        "p_capture_amount": capture_amount,
    })


def release_reservation(settings: Settings, *, user_id: str, reservation_id: str) -> dict:
    uid = _validate_user_id(user_id)
    rid = str(UUID(reservation_id))
    return _rpc(settings, "release_user_credit_reservation", {
        "p_user_id": uid,
        "p_reservation_id": rid,
    })


def mark_reconciliation_required(
    settings: Settings, *, user_id: str, reservation_id: str
) -> dict:
    """Keep funds reserved when provider completion is ambiguous; never refund blindly."""
    uid = _validate_user_id(user_id)
    rid = str(UUID(reservation_id))
    return _rpc(settings, "mark_credit_reservation_reconciliation_required", {
        "p_user_id": uid,
        "p_reservation_id": rid,
    })



def reserve_priced_ai_operation(
    settings: Settings,
    *,
    user_id: str,
    idempotency_key: str,
    operation_code: str,
    provider: str,
    model: str,
    catalog: dict[tuple[str, str, str], AIPricingRule] = AI_PRICING_CATALOG,
) -> tuple[PricingQuote, dict]:
    """Calculate a server-owned quote, then reserve that exact amount atomically."""
    quote = quote_ai_operation(
        operation_code=operation_code,
        provider=provider,
        model=model,
        catalog=catalog,
    )
    reservation = reserve_credits(
        settings,
        user_id=user_id,
        idempotency_key=idempotency_key,
        operation_code=quote.operation_code,
        pricing_version=quote.pricing_version,
        amount=quote.reserved_credits,
    )
    return quote, reservation


def settle_priced_ai_operation(
    settings: Settings,
    *,
    user_id: str,
    reservation_id: str,
    quote: PricingQuote,
    provider: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    catalog: dict[tuple[str, str, str], AIPricingRule] = AI_PRICING_CATALOG,
) -> tuple[PricingSettlement, dict]:
    """Settle trusted usage; ambiguous/unpriceable usage is held for reconciliation."""
    try:
        settlement = settle_ai_operation(
            quote,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            catalog=catalog,
        )
    except PricingError:
        mark_reconciliation_required(
            settings, user_id=user_id, reservation_id=reservation_id
        )
        raise
    result = settle_reservation(
        settings,
        user_id=user_id,
        reservation_id=reservation_id,
        capture_amount=settlement.captured_credits,
    )
    return settlement, result
