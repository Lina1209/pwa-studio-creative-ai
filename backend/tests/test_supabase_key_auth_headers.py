"""Service-role authentication header compatibility tests.

These tests mock HTTP transport and never contact Supabase.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import messaging_service, notification_service, profile_service


SERVICES = (
    messaging_service,
    notification_service,
    profile_service,
)


class SupabaseKeyHeaderTests(unittest.TestCase):
    def _settings(self, key):
        return SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key=key,
        )

    def _call(self, service, key):
        response = SimpleNamespace(content=b"[]", json=lambda: [], raise_for_status=lambda: None)
        with patch.object(service.httpx, "request", return_value=response) as request:
            if service is messaging_service:
                service._request(self._settings(key), "GET", "conversation_threads")
            else:
                service._request(self._settings(key), "GET")
            return request.call_args.kwargs["headers"]

    def test_new_secret_key_is_apikey_only_for_all_services(self):
        for service in SERVICES:
            with self.subTest(service=service.__name__):
                headers = self._call(service, "sb_secret_test_value")
                self.assertEqual(headers["apikey"], "sb_secret_test_value")
                self.assertNotIn("Authorization", headers)

    def test_legacy_jwt_key_is_also_bearer_for_all_services(self):
        for service in SERVICES:
            with self.subTest(service=service.__name__):
                headers = self._call(service, "eyJlegacy.jwt")
                self.assertEqual(headers["apikey"], "eyJlegacy.jwt")
                self.assertEqual(headers["Authorization"], "Bearer eyJlegacy.jwt")


if __name__ == "__main__":
    unittest.main()
