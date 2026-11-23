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
