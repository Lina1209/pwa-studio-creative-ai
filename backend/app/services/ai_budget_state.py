"""Pure AI budget reservation state transitions.

This module deliberately has no database, provider, or monetary policy defaults.
It is a testable domain layer only; it does not enforce budgets until a reviewed
transactional persistence adapter and explicit policy are added.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum


class ReservationStatus(str, Enum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    UNKNOWN = "unknown"


class ReservationTransitionError(ValueError):
    """Raised when a reservation transition would violate ledger invariants."""


@dataclass(frozen=True)
class ReservationState:
    status: ReservationStatus
    reserved_usd: Decimal
    actual_usd: Decimal | None = None


def _money(value: Decimal | str | int) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ReservationTransitionError("invalid_money_amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ReservationTransitionError("invalid_money_amount")
    return amount


def create_reservation(reserved_usd: Decimal | str | int) -> ReservationState:
    """Create a pending reservation amount calculated by trusted server code."""
    return ReservationState(
        status=ReservationStatus.RESERVED,
        reserved_usd=_money(reserved_usd),
    )


def mark_outcome_unknown(state: ReservationState) -> ReservationState:
    """Keep exposure reserved when provider outcome or charge is uncertain."""
    if state.status == ReservationStatus.RESERVED:
        return ReservationState(ReservationStatus.UNKNOWN, state.reserved_usd)
    if state.status == ReservationStatus.UNKNOWN:
        return state
    raise ReservationTransitionError("reservation_not_open")


def settle_reservation(
    state: ReservationState, actual_usd: Decimal | str | int | None
) -> ReservationState:
    """Settle known provider cost; unknown cost remains reserved for reconciliation."""
    if actual_usd is None:
        return mark_outcome_unknown(state)
    actual = _money(actual_usd)
    if state.status in (ReservationStatus.RESERVED, ReservationStatus.UNKNOWN):
        return ReservationState(ReservationStatus.SETTLED, state.reserved_usd, actual)
    if state.status == ReservationStatus.SETTLED and state.actual_usd == actual:
        return state
    raise ReservationTransitionError("conflicting_terminal_transition")


def release_reservation(
    state: ReservationState, *, provider_confirmed_no_charge: bool
) -> ReservationState:
    """Release only when the provider definitively confirms no charge occurred."""
    if not provider_confirmed_no_charge:
        return mark_outcome_unknown(state)
    if state.status in (ReservationStatus.RESERVED, ReservationStatus.UNKNOWN):
        return ReservationState(ReservationStatus.RELEASED, state.reserved_usd)
    if state.status == ReservationStatus.RELEASED:
        return state
    raise ReservationTransitionError("conflicting_terminal_transition")


def outstanding_reservation_usd(states: list[ReservationState]) -> Decimal:
    """Return reserved exposure; unknown outcomes remain counted conservatively."""
    return sum(
        (
            state.reserved_usd
            for state in states
            if state.status in (ReservationStatus.RESERVED, ReservationStatus.UNKNOWN)
        ),
        Decimal("0"),
    )
