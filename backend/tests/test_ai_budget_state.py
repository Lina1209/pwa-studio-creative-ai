import unittest
from decimal import Decimal

from app.services.ai_budget_state import (
    ReservationState,
    ReservationStatus,
    ReservationTransitionError,
    create_reservation,
    mark_outcome_unknown,
    outstanding_reservation_usd,
    release_reservation,
    settle_reservation,
)


class AIBudgetReservationStateTests(unittest.TestCase):
    def test_create_reservation_uses_trusted_amount_without_policy_default(self):
        state = create_reservation("0.0125")
        self.assertEqual(state.status, ReservationStatus.RESERVED)
        self.assertEqual(state.reserved_usd, Decimal("0.0125"))
        self.assertIsNone(state.actual_usd)

    def test_unknown_provider_cost_does_not_settle_at_zero(self):
        state = settle_reservation(create_reservation("0.02"), None)
        self.assertEqual(state.status, ReservationStatus.UNKNOWN)
        self.assertIsNone(state.actual_usd)
        self.assertEqual(outstanding_reservation_usd([state]), Decimal("0.02"))

    def test_timeout_keeps_reserved_exposure(self):
        state = mark_outcome_unknown(create_reservation("0.03"))
        self.assertEqual(outstanding_reservation_usd([state]), Decimal("0.03"))

    def test_known_cost_settles_from_reserved_or_unknown(self):
        for initial in (create_reservation("0.03"), mark_outcome_unknown(create_reservation("0.03"))):
            settled = settle_reservation(initial, "0.018")
            self.assertEqual(settled.status, ReservationStatus.SETTLED)
            self.assertEqual(settled.actual_usd, Decimal("0.018"))
            self.assertEqual(outstanding_reservation_usd([settled]), Decimal("0"))

    def test_settlement_is_idempotent_for_same_actual_cost(self):
        settled = settle_reservation(create_reservation("0.03"), "0.01")
        self.assertEqual(settle_reservation(settled, "0.01"), settled)

    def test_conflicting_second_settlement_is_rejected(self):
        settled = settle_reservation(create_reservation("0.03"), "0.01")
        with self.assertRaises(ReservationTransitionError):
            settle_reservation(settled, "0.02")

    def test_release_requires_confirmed_no_charge(self):
        initial = create_reservation("0.03")
        unknown = release_reservation(initial, provider_confirmed_no_charge=False)
        self.assertEqual(unknown.status, ReservationStatus.UNKNOWN)
        released = release_reservation(unknown, provider_confirmed_no_charge=True)
        self.assertEqual(released.status, ReservationStatus.RELEASED)
        self.assertEqual(outstanding_reservation_usd([released]), Decimal("0"))

    def test_release_is_idempotent(self):
        initial = create_reservation("0.03")
        released = release_reservation(initial, provider_confirmed_no_charge=True)
        self.assertEqual(release_reservation(released, provider_confirmed_no_charge=True), released)

    def test_settled_reservation_cannot_be_released(self):
        settled = settle_reservation(create_reservation("0.03"), "0.01")
        with self.assertRaises(ReservationTransitionError):
            release_reservation(settled, provider_confirmed_no_charge=True)

    def test_negative_nan_and_infinite_amounts_are_rejected(self):
        for amount in ("-0.01", "NaN", "Infinity"):
            with self.subTest(amount=amount), self.assertRaises(ReservationTransitionError):
                create_reservation(amount)

    def test_unknown_state_is_idempotent(self):
        unknown = mark_outcome_unknown(create_reservation("0.01"))
        self.assertEqual(mark_outcome_unknown(unknown), unknown)

    def test_exposure_sums_reserved_and_unknown_only(self):
        states = [
            create_reservation("0.01"),
            mark_outcome_unknown(create_reservation("0.02")),
            settle_reservation(create_reservation("0.03"), "0.025"),
            release_reservation(create_reservation("0.04"), provider_confirmed_no_charge=True),
        ]
        self.assertEqual(outstanding_reservation_usd(states), Decimal("0.03"))


if __name__ == "__main__":
    unittest.main()
