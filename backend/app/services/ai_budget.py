"""Provider-independent orchestration contract for future AI budget enforcement.

No persistence adapter is wired here. A transactional RPC implementation must
satisfy AIBudgetStore before this service is connected to API routes.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Protocol, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class AIReservationRequest:
    user_id: str
    request_id: str
    endpoint: str
    provider: str
    model: str
    request_fingerprint: str
    idempotency_key: str
    reserved_usd: Decimal


@dataclass(frozen=True)
class AIReservation:
    reservation_id: str
    reserved_usd: Decimal
    status: str = "reserved"
    created: bool = True


class AIBudgetDuplicateRequest(RuntimeError):
    """An idempotent reservation already exists; do not call the provider again."""


class AIBudgetStore(Protocol):
    """Transactional storage contract; implementations must be idempotent."""

    def reserve(self, request: AIReservationRequest) -> AIReservation:
        """Atomically enforce all enabled policies and persist reservation."""
        ...

    def settle(self, reservation_id: str, actual_cost_usd: Decimal | None) -> None:
        """Settle known cost; None MUST preserve exposure as unknown."""
        ...

    def mark_unknown(self, reservation_id: str, safe_reason: str) -> None:
        """Keep the reservation counted until provider outcome is reconciled."""
        ...

    def release_confirmed_no_charge(self, reservation_id: str, safe_reason: str) -> None:
        """Release only after authoritative confirmation that no charge occurred."""
        ...


class AIBudgetSettlementError(RuntimeError):
    """Provider succeeded but financial settlement could not be confirmed."""


def execute_reserved_ai_call(
    store: AIBudgetStore,
    request: AIReservationRequest,
    provider_call: Callable[[], T],
    *,
    cost_getter: Callable[[T], Decimal | None],
) -> T:
    """Reserve before provider call and conservatively close its accounting state.

    Provider exceptions are treated as unknown, not automatically as free:
    network failures can happen after a provider accepted and billed a request.
    """
    reservation = store.reserve(request)
    if not reservation.created or reservation.status != "reserved":
        raise AIBudgetDuplicateRequest("AI request was already reserved or processed.")
    try:
        result = provider_call()
    except Exception:
        # Best effort: preserve the provider exception even if the DB is unavailable.
        # Never release exposure on an ambiguous provider outcome.
        try:
            store.mark_unknown(reservation.reservation_id, "provider_outcome_unknown")
        except Exception:
            pass
        raise

    try:
        actual_cost = cost_getter(result)
        store.settle(reservation.reservation_id, actual_cost)
    except Exception as exc:
        try:
            store.mark_unknown(reservation.reservation_id, "settlement_unconfirmed")
        except Exception:
            # The original settlement failure remains the actionable exception.
            pass
        raise AIBudgetSettlementError("AI budget settlement is unconfirmed.") from exc
    return result
