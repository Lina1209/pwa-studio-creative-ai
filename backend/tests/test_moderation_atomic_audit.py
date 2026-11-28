"""Unit tests for the moderation service's single-transaction RPC boundary.

Run from backend/: python -m unittest discover -s tests -p 'test_*.py'
These tests verify routing/wiring only; the disposable-Supabase SQL test plan separately
verifies rollback when the audit insert fails.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.services import moderation_service


SETTINGS = SimpleNamespace(supabase_url="https://example.supabase.co", supabase_service_role_key="test-only")
MODERATOR = "11111111-1111-4111-8111-111111111111"
TARGET = "22222222-2222-4222-8222-222222222222"
REPORT = "33333333-3333-4333-8333-333333333333"
SUSPENSION = "44444444-4444-4444-8444-444444444444"


class ModerationAtomicAuditTests(unittest.TestCase):
    @patch.object(moderation_service.httpx, "request")
    def test_new_supabase_secret_key_is_not_sent_as_bearer_jwt(self, request):
        request.return_value = SimpleNamespace(content=b"[]", json=lambda: [], raise_for_status=lambda: None)
        settings = SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="sb_secret_test_key",
        )
        moderation_service._request(settings, "GET", "user_reports")
        headers = request.call_args.kwargs["headers"]
        self.assertEqual(headers["apikey"], "sb_secret_test_key")
        self.assertNotIn("Authorization", headers)

    @patch.object(moderation_service.httpx, "request")
    def test_legacy_service_role_jwt_is_sent_as_bearer(self, request):
        request.return_value = SimpleNamespace(content=b"[]", json=lambda: [], raise_for_status=lambda: None)
        settings = SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="eyJlegacy.jwt",
        )
        moderation_service._request(settings, "GET", "user_reports")
        headers = request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer eyJlegacy.jwt")

    @patch.object(moderation_service, "_request")
    def test_review_uses_one_atomic_rpc(self, request):
        expected = {"id": REPORT, "status": "resolved", "reporter_user_id": TARGET}
        request.return_value = expected
        result = moderation_service.review_user_report(
            SETTINGS, REPORT, MODERATOR,
            SimpleNamespace(status="resolved", moderator_note="Reviewed"),
        )
        self.assertEqual(result, expected)
        request.assert_called_once_with(
            SETTINGS, "POST", "rpc/pwa_review_user_report",
            payload={"p_report_id": REPORT, "p_moderator_id": MODERATOR,
                     "p_status": "resolved", "p_moderator_note": "Reviewed"},
        )

    @patch.object(moderation_service, "_request")
    def test_create_suspension_uses_one_atomic_rpc(self, request):
        expected = {"id": SUSPENSION, "user_id": TARGET, "scope": "community"}
        request.return_value = expected
        result = moderation_service.create_suspension(
            SETTINGS, MODERATOR,
            SimpleNamespace(user_id=TARGET, reason="Repeated abuse",
                            scope="community", expires_at=None),
        )
        self.assertEqual(result, expected)
        request.assert_called_once_with(
            SETTINGS, "POST", "rpc/pwa_create_user_suspension",
            payload={"p_user_id": TARGET, "p_moderator_id": MODERATOR,
                     "p_reason": "Repeated abuse", "p_scope": "community",
                     "p_expires_at": None},
        )

    @patch.object(moderation_service, "_request")
    def test_revoke_uses_one_atomic_rpc(self, request):
        request.return_value = {"id": SUSPENSION}
        result = moderation_service.revoke_suspension(SETTINGS, MODERATOR, SUSPENSION)
        self.assertEqual(result, {"success": True, "id": SUSPENSION})
        request.assert_called_once_with(
            SETTINGS, "POST", "rpc/pwa_revoke_user_suspension",
            payload={"p_suspension_id": SUSPENSION, "p_moderator_id": MODERATOR},
        )

    @patch.object(moderation_service, "_request")
    def test_rpc_failure_is_not_followed_by_a_separate_audit_write(self, request):
        request.side_effect = HTTPException(status_code=502, detail="simulated RPC failure")
        with self.assertRaises(HTTPException):
            moderation_service.review_user_report(
                SETTINGS, REPORT, MODERATOR,
                SimpleNamespace(status="resolved", moderator_note=None),
            )
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
