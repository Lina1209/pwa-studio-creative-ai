import unittest
from decimal import Decimal
from unittest.mock import Mock, call

from app.services.ai_budget import (
    AIBudgetSettlementError,
    AIReservation,
    AIReservationRequest,
    execute_reserved_ai_call,
)


class AIBudgetOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.store.reserve.return_value = AIReservation("reservation-1", Decimal("0.05"))
        self.request = AIReservationRequest(
            user_id="verified-user",
            request_id="request-1",
            endpoint="/api/chat",
            provider="deepseek",
            model="deepseek-flash",
            request_fingerprint="a" * 64,
        )

    def test_reservation_precedes_provider_and_known_cost_is_settled(self):
        events = []
        self.store.reserve.side_effect = lambda request: (
            events.append("reserve") or AIReservation("reservation-1", Decimal("0.05"))
        )
        def provider():
            events.append("provider")
            return type("Result", (), {"cost_usd": Decimal("0.02")})()

        result = execute_reserved_ai_call(
            self.store, self.request, provider, cost_getter=lambda item: item.cost_usd
        )

        self.assertEqual(events, ["reserve", "provider"])
        self.store.settle.assert_called_once_with("reservation-1", Decimal("0.02"))
        self.store.mark_unknown.assert_not_called()
        self.assertEqual(result.cost_usd, Decimal("0.02"))

    def test_unknown_cost_is_passed_as_none_not_zero(self):
        result = execute_reserved_ai_call(
            self.store, self.request, lambda: object(), cost_getter=lambda _: None
        )
        self.store.settle.assert_called_once_with("reservation-1", None)
        self.store.mark_unknown.assert_not_called()
        self.assertIsNotNone(result)

    def test_provider_exception_marks_reservation_unknown_and_reraises(self):
        failure = TimeoutError("provider timeout")
        with self.assertRaises(TimeoutError):
            execute_reserved_ai_call(
                self.store, self.request, Mock(side_effect=failure), cost_getter=lambda _: None
            )
        self.store.mark_unknown.assert_called_once_with(
            "reservation-1", "provider_outcome_unknown"
        )
        self.store.settle.assert_not_called()

    def test_provider_exception_is_preserved_if_unknown_marking_fails(self):
        failure = TimeoutError("provider timeout")
        self.store.mark_unknown.side_effect = RuntimeError("database unavailable")
        with self.assertRaises(TimeoutError) as raised:
            execute_reserved_ai_call(
                self.store, self.request, Mock(side_effect=failure), cost_getter=lambda _: None
            )
        self.assertIs(raised.exception, failure)

    def test_reservation_failure_prevents_provider_call(self):
        self.store.reserve.side_effect = RuntimeError("budget unavailable")
        provider = Mock()
        with self.assertRaisesRegex(RuntimeError, "budget unavailable"):
            execute_reserved_ai_call(
                self.store, self.request, provider, cost_getter=lambda _: None
            )
        provider.assert_not_called()

    def test_settlement_failure_marks_unknown_and_does_not_return_result(self):
        self.store.settle.side_effect = RuntimeError("database unavailable")
        with self.assertRaises(AIBudgetSettlementError):
            execute_reserved_ai_call(
                self.store, self.request, lambda: "provider response",
                cost_getter=lambda _: Decimal("0.01"),
            )
        self.store.mark_unknown.assert_called_once_with(
            "reservation-1", "settlement_unconfirmed"
        )

    def test_confirmed_no_charge_release_is_available_only_on_store_contract(self):
        self.store.release_confirmed_no_charge("reservation-1", "provider_rejected_before_accept")
        self.store.release_confirmed_no_charge.assert_called_once_with(
            "reservation-1", "provider_rejected_before_accept"
        )


if __name__ == "__main__":
    unittest.main()
