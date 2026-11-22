"""Fail-closed decisions for reconciling ambiguous external image operations.

This pure policy module performs no network or database I/O. Adapters and the
worker must persist journal state and execute only the returned decision.
"""
from dataclasses import dataclass

from app.services.image_generation import ImageGenerationLookup


@dataclass(frozen=True)
class ProviderRecoveryDecision:
    action: str
    error_code: str | None = None


def decide_provider_recovery(
    lookup: ImageGenerationLookup,
    *,
    supports_idempotency: bool,
    supports_lookup: bool,
) -> ProviderRecoveryDecision:
    """Choose a safe next action without ever treating uncertainty as absence."""
    if not supports_lookup:
        return ProviderRecoveryDecision("quarantine", "provider_lookup_not_supported")

    if lookup.status == "succeeded":
        return ProviderRecoveryDecision("use_existing_result")
    if lookup.status == "pending":
        return ProviderRecoveryDecision("wait", "provider_operation_pending")
    if lookup.status == "failed":
        # Provider-confirmed terminal failure is safe to surface as failure.
        return ProviderRecoveryDecision("fail", lookup.error_code or "provider_operation_failed")
    if lookup.status == "not_found":
        # A negative lookup is not sufficient by itself unless provider-side
        # idempotency also guarantees that a repeated submission is deduplicated.
        if supports_idempotency:
            return ProviderRecoveryDecision("resubmit_same_key")
        return ProviderRecoveryDecision("quarantine", "provider_operation_not_recoverable")

    return ProviderRecoveryDecision("quarantine", "provider_operation_status_unknown")
