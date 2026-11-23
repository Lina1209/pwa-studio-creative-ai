"""Provider webhook verification contract.

Concrete provider adapters must verify the provider's signature over the exact
raw request bytes before returning normalized event facts. No generic verifier
is supplied because signature schemes and canonicalization are provider-specific.
"""
from dataclasses import dataclass
from typing import Mapping, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VerifiedProviderEvent:
    provider_event_id: str
    payment_order_id: UUID
    event_type: str
    amount_minor: int
    currency_code: str
    provider_payment_id: str


class PaymentProviderWebhookAdapter(Protocol):
    """Trusted, provider-specific adapter configured only on the server."""

    @property
    def provider_code(self) -> str:
        """Stable lowercase provider/account namespace used by payment orders."""

    def verify_webhook(
        self, *, raw_body: bytes, headers: Mapping[str, str]
    ) -> VerifiedProviderEvent:
        """Verify signature/timestamp/replay window, then normalize the payload.

        Implementations must fail closed. They must not return an event before
        cryptographic verification succeeds, and must derive every normalized
        field from the authenticated payload rather than caller-supplied values.
        """

class PaymentProviderNotConfigured(RuntimeError):
    """Raised when a provider has no explicitly configured server adapter."""


class PaymentProviderAdapterRegistry:
    """Immutable allowlist of server-configured provider adapters.

    An empty registry is valid and intentionally means that payment webhooks
    cannot be processed. Adapters are never selected from request data.
    """

    def __init__(self, adapters=()):
        from types import MappingProxyType
        import re

        registered = {}
        for adapter in adapters:
            code = getattr(adapter, "provider_code", None)
            verifier = getattr(adapter, "verify_webhook", None)
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", code):
                raise ValueError("Payment provider adapter identity is invalid.")
            if not callable(verifier):
                raise ValueError("Payment provider adapter has no verifier.")
            if code in registered:
                raise ValueError("Duplicate payment provider adapter identity.")
            registered[code] = adapter
        self._adapters = MappingProxyType(registered)

    def get(self, provider_code: str) -> PaymentProviderWebhookAdapter:
        if not isinstance(provider_code, str):
            raise PaymentProviderNotConfigured("Payment provider is not configured.")
        try:
            return self._adapters[provider_code]
        except KeyError as exc:
            raise PaymentProviderNotConfigured(
                "Payment provider is not configured."
            ) from exc

    @property
    def provider_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
