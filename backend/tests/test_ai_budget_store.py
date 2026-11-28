import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.config import Settings
from app.services.ai_budget import AIReservationRequest
from app.services.ai_budget_store import (
    AIBudgetStoreUnavailable,
    SupabaseAIBudgetStore,
)


class SupabaseAIBudgetStoreTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="eyJ-test-service-role",
        )
        self.store = SupabaseAIBudgetStore(self.settings)
        self.request = AIReservationRequest(
            user_id="11111111-1111-4111-8111-111111111111",
            request_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            endpoint="chat",
            provider="deepseek",
            model="deepseek-flash",
            request_fingerprint="a" * 64,
            idempotency_key="request-idempotency-0001",
            reserved_usd=Decimal("0.025"),
        )

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_reserve_sends_server_calculated_fields_to_private_rpc(self, client_cls):
        response = MagicMock()
        response.json.return_value = [{
            "reservation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "reservation_status": "reserved",
            "reserved_usd": "0.0250000000",
            "reservation_created": True,
        }]
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = response

        reservation = self.store.reserve(self.request)

        self.assertEqual(reservation.reservation_id, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        self.assertEqual(reservation.reserved_usd, Decimal("0.0250000000"))
        self.assertTrue(reservation.created)
        args = client.post.call_args
        self.assertTrue(args.args[0].endswith("/rpc/reserve_ai_budget"))
        self.assertEqual(args.kwargs["json"]["p_user_id"], self.request.user_id)
        self.assertEqual(args.kwargs["json"]["p_reserved_usd"], "0.025")
        self.assertEqual(args.kwargs["headers"]["Authorization"], "Bearer eyJ-test-service-role")

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_reserve_rejects_malformed_reservation_uuid(self, client_cls):
        client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = [{
            "reservation_id": "not-a-uuid",
            "reservation_status": "reserved",
            "reserved_usd": "0.025",
            "reservation_created": True,
        }]
        with self.assertRaises(AIBudgetStoreUnavailable):
            self.store.reserve(self.request)

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_reserve_rejects_unknown_rpc_status(self, client_cls):
        client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = [{
            "reservation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "reservation_status": "completed_unrecognized",
            "reserved_usd": "0.025",
            "reservation_created": True,
        }]
        with self.assertRaises(AIBudgetStoreUnavailable):
            self.store.reserve(self.request)

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_reserve_rejects_created_flag_with_non_reserved_state(self, client_cls):
        client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = [{
            "reservation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "reservation_status": "settled",
            "reserved_usd": "0.025",
            "reservation_created": True,
        }]
        with self.assertRaises(AIBudgetStoreUnavailable):
            self.store.reserve(self.request)

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_reserve_rejects_non_boolean_created_flag(self, client_cls):
        client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = [{
            "reservation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "reservation_status": "reserved",
            "reserved_usd": "0.025",
            "reservation_created": "true",
        }]
        with self.assertRaises(AIBudgetStoreUnavailable):
            self.store.reserve(self.request)

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_duplicate_reservation_is_reported_without_fabricating_new_state(self, client_cls):
        response = MagicMock()
        response.json.return_value = [{
            "reservation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "reservation_status": "reserved",
            "reserved_usd": "0.025",
            "reservation_created": False,
        }]
        client_cls.return_value.__enter__.return_value.post.return_value = response
        reservation = self.store.reserve(self.request)
        self.assertFalse(reservation.created)

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_unknown_cost_calls_unknown_rpc_not_zero_settlement(self, client_cls):
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.json.return_value = True
        self.store.settle("reservation-1", None)
        self.assertTrue(client.post.call_args.args[0].endswith("/rpc/mark_ai_budget_unknown"))
        self.assertEqual(client.post.call_args.kwargs["json"]["p_safe_reason"], "provider_cost_unknown")

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_known_cost_calls_settlement_rpc(self, client_cls):
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.json.return_value = "settled"
        self.store.settle("reservation-1", Decimal("0.01"))
        self.assertTrue(client.post.call_args.args[0].endswith("/rpc/settle_ai_budget"))
        self.assertEqual(client.post.call_args.kwargs["json"]["p_actual_usd"], "0.01")

    def test_settlement_rejects_non_finite_and_negative_amounts_before_rpc(self):
        for amount in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), Decimal("-0.01")):
            with self.subTest(amount=amount):
                with patch("app.services.ai_budget_store.httpx.Client") as client_cls:
                    with self.assertRaises(ValueError):
                        self.store.settle("reservation-1", amount)
                    client_cls.assert_not_called()

    def test_settlement_rejects_non_decimal_amount_before_rpc(self):
        with patch("app.services.ai_budget_store.httpx.Client") as client_cls:
            with self.assertRaises(ValueError):
                self.store.settle("reservation-1", 0.01)
            client_cls.assert_not_called()

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_confirmed_no_charge_uses_dedicated_release_rpc(self, client_cls):
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.json.return_value = True
        self.store.release_confirmed_no_charge("reservation-1", "provider_rejected")
        self.assertTrue(client.post.call_args.args[0].endswith("/rpc/release_ai_budget_no_charge"))

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_secret_key_is_not_misused_as_bearer_jwt(self, client_cls):
        settings = Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="sb_secret_test_key",
        )
        store = SupabaseAIBudgetStore(settings)
        client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = [{
            "reservation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "reservation_status": "reserved",
            "reserved_usd": "0.025",
            "reservation_created": True,
        }]
        store.reserve(self.request)
        headers = client_cls.return_value.__enter__.return_value.post.call_args.kwargs["headers"]
        self.assertEqual(headers["apikey"], "sb_secret_test_key")
        self.assertNotIn("Authorization", headers)

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_rpc_failure_is_sanitized(self, client_cls):
        client_cls.return_value.__enter__.return_value.post.side_effect = RuntimeError("secret response body")
        with self.assertRaises(AIBudgetStoreUnavailable) as raised:
            self.store.reserve(self.request)
        self.assertNotIn("secret response body", str(raised.exception))

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_missing_settlement_is_not_reported_as_success(self, client_cls):
        client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = "not_found"
        with self.assertRaises(AIBudgetStoreUnavailable):
            self.store.settle("missing-reservation", Decimal("0.01"))

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_unconfirmed_release_is_not_reported_as_success(self, client_cls):
        client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = False
        with self.assertRaises(AIBudgetStoreUnavailable):
            self.store.release_confirmed_no_charge("missing-reservation", "provider_rejected")

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_stale_reconciliation_calls_safe_unknown_rpc(self, client_cls):
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.json.return_value = 3
        count = self.store.mark_stale_reservations_unknown("2026-11-28T00:00:00Z", 25)
        self.assertEqual(count, 3)
        self.assertTrue(client.post.call_args.args[0].endswith(
            "/rpc/mark_stale_ai_budget_reservations_unknown"
        ))
        self.assertEqual(client.post.call_args.kwargs["json"]["p_limit"], 25)

    def test_stale_reconciliation_rejects_invalid_batch_size(self):
        with self.assertRaises(ValueError):
            self.store.mark_stale_reservations_unknown("2026-11-28T00:00:00Z", 0)

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_reconciliation_candidates_are_returned_without_extra_fields(self, client_cls):
        rows = [{
            "reservation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "request_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "user_id": "11111111-1111-4111-8111-111111111111",
            "endpoint": "chat",
            "provider": "deepseek",
            "model": "deepseek-flash",
            "reservation_status": "unknown",
            "reserved_usd": "0.025",
            "created_at": "2026-11-28T00:00:00Z",
            "updated_at": "2026-11-28T00:01:00Z",
        }]
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.json.return_value = rows
        result = self.store.list_reconciliation_candidates(20)
        self.assertEqual(result, rows)
        self.assertTrue(client.post.call_args.args[0].endswith(
            "/rpc/list_ai_budget_reconciliation_candidates"
        ))
        self.assertEqual(client.post.call_args.kwargs["json"], {"p_limit": 20})

    def test_reconciliation_candidates_reject_invalid_limit(self):
        with self.assertRaises(ValueError):
            self.store.list_reconciliation_candidates(1001)

    @patch("app.services.ai_budget_store.httpx.Client")
    def test_reserve_rejects_rpc_amount_different_from_requested(self, client_cls):
        client_cls.return_value.__enter__.return_value.post.return_value.json.return_value = [{
            "reservation_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "reservation_status": "reserved",
            "reserved_usd": "0.024",
            "reservation_created": True,
        }]
        with self.assertRaises(AIBudgetStoreUnavailable):
            self.store.reserve(self.request)

    def test_reconciliation_limits_reject_boolean_and_non_integer(self):
        for limit in (True, False, 1.5, "10"):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.store.list_reconciliation_candidates(limit)
                with self.assertRaises(ValueError):
                    self.store.mark_stale_reservations_unknown("2026-11-28T00:00:00Z", limit)

    def test_missing_server_credentials_fail_closed(self):
        store = SupabaseAIBudgetStore(Settings())
        with self.assertRaises(AIBudgetStoreUnavailable):
            store.reserve(self.request)


if __name__ == "__main__":
    unittest.main()
