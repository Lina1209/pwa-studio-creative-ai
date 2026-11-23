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

    def validate_configuration(self, settings: object) -> None:
        """Validate required provider-specific server settings; never log secrets."""

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

    def __init__(self, adapters=(), *, enabled: bool = False, settings=None):
        from types import MappingProxyType
        import re

        if not isinstance(enabled, bool):
            raise ValueError("Payment provider runtime flag must be boolean.")
        if enabled and (settings is None or getattr(settings, "payment_provider_runtime_enabled", False) is not True):
            raise PaymentProviderNotConfigured("Payment provider runtime is disabled.")
        registered = {}
        for adapter in adapters:
            code = getattr(adapter, "provider_code", None)
            verifier = getattr(adapter, "verify_webhook", None)
            if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", code):
                raise ValueError("Payment provider adapter identity is invalid.")
            if not callable(verifier):
                raise ValueError("Payment provider adapter has no verifier.")
            validator = getattr(adapter, "validate_configuration", None)
            if enabled and not callable(validator):
                raise ValueError("Payment provider adapter has no configuration validator.")
            if enabled:
                # Provider-specific code validates required credentials, account scope,
                # webhook secret and environment. It must fail closed and never log them.
                validator(settings)
            if code in registered:
                raise ValueError("Duplicate payment provider adapter identity.")
            registered[code] = adapter
        self._adapters = MappingProxyType(registered)
        self._enabled = enabled

    def get(self, provider_code: str) -> PaymentProviderWebhookAdapter:
        if not self._enabled:
            raise PaymentProviderNotConfigured("Payment provider runtime is disabled.")
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
