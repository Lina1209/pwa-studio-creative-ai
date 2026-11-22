"""Server-owned, versioned generation pricing and signed quote primitives.

No production catalog is shipped: operators must approve concrete prices before
any quote can be issued. Browser-supplied amounts are never accepted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4


class PricingError(ValueError):
    pass


@dataclass(frozen=True)
class PricingRule:
    job_type: str
    provider: str
    model: str
    credits_per_unit: int
    unit_label: str
    min_quantity: int = 1
    max_quantity: int = 1

    def __post_init__(self) -> None:
        if not self.job_type or not self.provider or not self.model:
            raise PricingError("Pricing rule identity fields are required.")
        if isinstance(self.credits_per_unit, bool) or not isinstance(self.credits_per_unit, int) or self.credits_per_unit <= 0:
            raise PricingError("Pricing rule credit rate must be a positive integer.")
        if not self.unit_label or len(self.unit_label) > 40:
            raise PricingError("Pricing rule unit label is invalid.")
        if not 1 <= self.min_quantity <= self.max_quantity <= 10000:
            raise PricingError("Pricing rule quantity bounds are invalid.")


@dataclass(frozen=True)
class PricingCatalog:
    version: str
    rules: tuple[PricingRule, ...]

    def __post_init__(self) -> None:
        if not self.version or len(self.version) > 80:
            raise PricingError("Pricing catalog version is invalid.")
        identities = [(r.job_type, r.provider, r.model) for r in self.rules]
        if len(identities) != len(set(identities)):
            raise PricingError("Pricing catalog contains duplicate rules.")

    def find(self, job_type: str, provider: str, model: str) -> PricingRule:
        for rule in self.rules:
            if (rule.job_type, rule.provider, rule.model) == (job_type, provider, model):
                return rule
        raise PricingError("No approved price exists for this generation configuration.")


@dataclass(frozen=True)
class VerifiedPricingQuote:
    quote_id: UUID
    user_id: UUID
    job_type: str
    provider: str
    model: str
    request_hash: str
    idempotency_key: str
    quantity: int
    unit_label: str
    amount: int
    price_version: str
    issued_at: datetime
    expires_at: datetime
    signature: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "pwa-studio-pricing-quote-v1",
            "quote_id": str(self.quote_id),
            "user_id": str(self.user_id),
            "job_type": self.job_type,
            "provider": self.provider,
            "model": self.model,
            "request_hash": self.request_hash,
            "idempotency_key": self.idempotency_key,
            "quantity": self.quantity,
            "unit_label": self.unit_label,
            "credit_unit": "credit",
            "amount": self.amount,
            "maximum_authorized_charge": self.amount,
            "price_version": self.price_version,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "signature": self.signature,
        }


def canonical_request_hash(request_snapshot: dict[str, Any]) -> str:
    if not isinstance(request_snapshot, dict):
        raise PricingError("Generation request snapshot must be an object.")
    try:
        encoded = json.dumps(
            request_snapshot, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PricingError("Generation request snapshot is not canonical JSON.") from exc
    if len(encoded) > 65536:
        raise PricingError("Generation request snapshot exceeds 64 KiB.")
    return hashlib.sha256(encoded).hexdigest()


def _quote_payload(
    *, quote_id: UUID, user_id: UUID, job_type: str, provider: str,
    model: str, request_hash: str, idempotency_key: str, quantity: int, unit_label: str,
    amount: int, price_version: str, issued_at: datetime, expires_at: datetime,
) -> dict[str, Any]:
    return {
        "schema": "pwa-studio-pricing-quote-v1",
        "quote_id": str(quote_id),
        "user_id": str(user_id),
        "job_type": job_type,
        "provider": provider,
        "model": model,
        "request_hash": request_hash,
        "idempotency_key": idempotency_key,
        "quantity": quantity,
        "unit_label": unit_label,
        "credit_unit": "credit",
        "amount": amount,
        "maximum_authorized_charge": amount,
        "price_version": price_version,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def _sign(payload: dict[str, Any], secret: str) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def issue_pricing_quote(
    *, secret: str | None, catalog: PricingCatalog, user_id: UUID,
    job_type: str, provider: str, model: str, request_hash: str,
    idempotency_key: str, quantity: int = 1, ttl_seconds: int = 600,
    now: datetime | None = None,
) -> VerifiedPricingQuote:
    if not secret or len(secret.encode("utf-8")) < 32:
        raise PricingError("Pricing quote signing secret is not configured securely.")
    if not isinstance(user_id, UUID):
        raise PricingError("Authenticated user identity is required.")
    if not isinstance(request_hash, str) or len(request_hash) != 64 or any(c not in "0123456789abcdef" for c in request_hash):
        raise PricingError("Canonical request hash must be lowercase SHA-256 hex.")
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 200:
        raise PricingError("Generation idempotency key is invalid.")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise PricingError("Generation quantity must be an integer.")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 30 <= ttl_seconds <= 1800:
        raise PricingError("Pricing quote lifetime must be between 30 and 1800 seconds.")

    rule = catalog.find(job_type, provider, model)
    if not rule.min_quantity <= quantity <= rule.max_quantity:
        raise PricingError("Requested quantity is outside the approved pricing bounds.")
    amount = rule.credits_per_unit * quantity
    if amount > 1_000_000_000_000:
        raise PricingError("Calculated quote exceeds the supported credit limit.")

    issued_at = now or datetime.now(timezone.utc)
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise PricingError("Quote clock must be timezone-aware.")
    issued_at = issued_at.astimezone(timezone.utc)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    quote_id = uuid4()
    payload = _quote_payload(
        quote_id=quote_id, user_id=user_id, job_type=job_type,
        provider=provider, model=model, request_hash=request_hash, idempotency_key=idempotency_key,
        quantity=quantity, unit_label=rule.unit_label, amount=amount,
        price_version=catalog.version, issued_at=issued_at, expires_at=expires_at,
    )
    return VerifiedPricingQuote(
        quote_id=quote_id, user_id=user_id, job_type=job_type,
        provider=provider, model=model, request_hash=request_hash,
        quantity=quantity, unit_label=rule.unit_label, amount=amount,
        price_version=catalog.version, issued_at=issued_at,
        expires_at=expires_at, signature=_sign(payload, secret),
    )


def verify_pricing_quote(
    snapshot: dict[str, Any], *, secret: str | None, user_id: UUID,
    job_type: str, provider: str, model: str, request_hash: str,
    idempotency_key: str, now: datetime | None = None,
) -> VerifiedPricingQuote:
    if not secret or len(secret.encode("utf-8")) < 32:
        raise PricingError("Pricing quote signing secret is not configured securely.")
    if not isinstance(snapshot, dict) or snapshot.get("schema") != "pwa-studio-pricing-quote-v1":
        raise PricingError("Pricing quote format is invalid.")
    try:
        quote_id = UUID(snapshot["quote_id"])
        quoted_user = UUID(snapshot["user_id"])
        quantity = snapshot["quantity"]
        amount = snapshot["amount"]
        issued_at = datetime.fromisoformat(snapshot["issued_at"])
        expires_at = datetime.fromisoformat(snapshot["expires_at"])
        signature = snapshot["signature"]
        quote_job_type = snapshot["job_type"]
        quote_provider = snapshot["provider"]
        quote_model = snapshot["model"]
        quote_hash = snapshot["request_hash"]
        quote_idempotency_key = snapshot["idempotency_key"]
        unit_label = snapshot["unit_label"]
        price_version = snapshot["price_version"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PricingError("Pricing quote is incomplete or malformed.") from exc

    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise PricingError("Pricing quote quantity is invalid.")
    if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= 1_000_000_000_000:
        raise PricingError("Pricing quote amount is invalid.")
    if snapshot.get("credit_unit") != "credit" or snapshot.get("maximum_authorized_charge") != amount:
        raise PricingError("Pricing quote authorization limit is inconsistent.")
    if (quoted_user, quote_job_type, quote_provider, quote_model, quote_hash) != (
        user_id, job_type, provider, model, request_hash
    ):
        raise PricingError("Pricing quote does not match this user or generation request.")
    if quote_idempotency_key != idempotency_key or not 8 <= len(idempotency_key) <= 200:
        raise PricingError("Pricing quote does not match this idempotency key.")
    if not all(isinstance(v, str) and v for v in (signature, unit_label, price_version)):
        raise PricingError("Pricing quote metadata is invalid.")
    if issued_at.tzinfo is None or expires_at.tzinfo is None:
        raise PricingError("Pricing quote timestamps must include a timezone.")
    issued_at = issued_at.astimezone(timezone.utc)
    expires_at = expires_at.astimezone(timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise PricingError("Quote verification clock must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    if expires_at <= current or issued_at > current + timedelta(seconds=30) or expires_at <= issued_at:
        raise PricingError("Pricing quote has expired or has an invalid validity window.")
    if expires_at - issued_at > timedelta(seconds=1800):
        raise PricingError("Pricing quote validity window exceeds the allowed maximum.")

    payload = _quote_payload(
        quote_id=quote_id, user_id=quoted_user, job_type=quote_job_type,
        provider=quote_provider, model=quote_model, request_hash=quote_hash, idempotency_key=quote_idempotency_key,
        quantity=quantity, unit_label=unit_label, amount=amount,
        price_version=price_version, issued_at=issued_at, expires_at=expires_at,
    )
    expected = _sign(payload, secret)
    if not hmac.compare_digest(signature, expected):
        raise PricingError("Pricing quote signature is invalid.")
    return VerifiedPricingQuote(
        quote_id=quote_id, user_id=quoted_user, job_type=quote_job_type,
        provider=quote_provider, model=quote_model, request_hash=quote_hash,
        quantity=quantity, unit_label=unit_label, amount=amount,
        price_version=price_version, issued_at=issued_at,
        expires_at=expires_at, signature=signature,
    )
