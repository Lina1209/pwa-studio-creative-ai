"""Admin identity and route-guard regression tests.

Run from backend/: python -m unittest discover -s tests -p 'test_*.py'
These tests use dependency overrides and mocked storage; no Supabase or production calls.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials

from app.main import app
from app.services import auth
from app.services.auth import StudioUser, get_current_user, require_admin


OWNER = "11111111-1111-4111-8111-111111111111"
CREATOR = "22222222-2222-4222-8222-222222222222"
ISSUER = "https://project.example.supabase.co/auth/v1"


class AdminIdentityTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    @patch.object(auth, "_jwks_client")
    @patch.object(auth, "get_settings")
    @patch.object(auth.jwt, "decode")
    def test_admin_role_comes_from_configured_immutable_user_id(self, decode, settings, jwks):
        settings.return_value = SimpleNamespace(
            supabase_url="https://project.example.supabase.co",
            owner_user_id=OWNER, owner_email="other@example.com")
        jwks.return_value.get_signing_key_from_jwt.return_value.key = "test-public-key"
        decode.return_value = {"sub": OWNER, "email": "changed@example.com"}
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token")
        user = get_current_user(credentials)
        self.assertEqual(user.role, "admin")
        decode.assert_called_once()
        self.assertEqual(decode.call_args.kwargs["issuer"], ISSUER)
        self.assertEqual(decode.call_args.kwargs["audience"], "authenticated")
        self.assertEqual(decode.call_args.kwargs["algorithms"], ["ES256", "RS256"])

    @patch.object(auth, "_jwks_client")
    @patch.object(auth, "get_settings")
    @patch.object(auth.jwt, "decode")
    def test_email_cannot_override_configured_owner_uuid(self, decode, settings, jwks):
        settings.return_value = SimpleNamespace(
            supabase_url="https://project.example.supabase.co",
            owner_user_id=OWNER, owner_email="creator@example.com")
        jwks.return_value.get_signing_key_from_jwt.return_value.key = "test-public-key"
        decode.return_value = {"sub": CREATOR, "email": "creator@example.com"}
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token")
        user = get_current_user(credentials)
        self.assertEqual(user.role, "creator")

    def test_missing_bearer_token_is_401(self):
        with patch.object(auth, "get_settings", return_value=SimpleNamespace(
            supabase_url="https://project.example.supabase.co")):
            with self.assertRaises(HTTPException) as caught:
                get_current_user(None)
        self.assertEqual(caught.exception.status_code, 401)

    def test_require_admin_rejects_creator(self):
        with self.assertRaises(HTTPException) as caught:
            require_admin(StudioUser(user_id=CREATOR, email=None, role="creator"))
        self.assertEqual(caught.exception.status_code, 403)

    def test_require_admin_accepts_server_resolved_admin(self):
        admin = StudioUser(user_id=OWNER, email=None, role="admin")
        self.assertIs(require_admin(admin), admin)


class AdminRouteGuardTests(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def _client_as(self, user):
        app.dependency_overrides[auth.get_current_user] = lambda: user
        return TestClient(app)

    def test_creator_is_denied_on_every_admin_route(self):
        client = self._client_as(StudioUser(CREATOR, None, "creator"))
        routes = [
            ("GET", "/api/admin/me"),
            ("GET", "/api/admin/reports"),
            ("PATCH", "/api/admin/reports/33333333-3333-4333-8333-333333333333"),
            ("GET", "/api/admin/suspensions"),
            ("POST", "/api/admin/suspensions"),
            ("POST", "/api/admin/suspensions/revoke"),
        ]
        for method, path in routes:
            response = client.request(method, path, json={} if method in {"PATCH", "POST"} else None)
            self.assertEqual(response.status_code, 403, f"{method} {path} was not forbidden")

    @patch("app.main.create_notification")
    @patch("app.main.review_user_report", return_value={
        "id": "33333333-3333-4333-8333-333333333333",
        "status": "resolved",
        "created_at": "2026-11-27T00:00:00Z",
        "reporter_user_id": CREATOR,
    })
    def test_report_review_uses_authenticated_admin_not_request_identity(self, review, notification):
        client = self._client_as(StudioUser(OWNER, None, "admin"))
        response = client.patch(
            "/api/admin/reports/33333333-3333-4333-8333-333333333333",
            json={"status": "resolved", "moderator_note": "Reviewed"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(review.call_args.args[2], OWNER)
        self.assertEqual(review.call_args.args[3].status, "resolved")

    @patch("app.main.ensure_target_not_owner")
    @patch("app.main.create_suspension", return_value={
        "id": "44444444-4444-4444-8444-444444444444",
        "user_id": CREATOR, "reason": "Repeated abuse", "scope": "community",
        "expires_at": None, "created_at": "2026-11-27T00:00:00Z",
    })
    def test_suspension_uses_authenticated_admin_not_request_identity(self, create, target_guard):
        client = self._client_as(StudioUser(OWNER, None, "admin"))
        response = client.post("/api/admin/suspensions", json={
            "user_id": CREATOR, "reason": "Repeated abuse", "scope": "community",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(create.call_args.args[1], OWNER)

    @patch("app.main.list_user_reports", return_value=[])
    @patch("app.main.list_suspensions", return_value=[])
    def test_admin_can_reach_read_only_admin_routes(self, suspensions, reports):
        client = self._client_as(StudioUser(OWNER, None, "admin"))
        self.assertEqual(client.get("/api/admin/me").status_code, 200)
        self.assertEqual(client.get("/api/admin/reports").status_code, 200)
        self.assertEqual(client.get("/api/admin/suspensions").status_code, 200)
        reports.assert_called_once()
        suspensions.assert_called_once()


if __name__ == "__main__":
    unittest.main()
