import unittest
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from app.core.config import Settings
from app.services.ai_service import AIResult
from app.services.usage_service import record_ai_usage


class UsageTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.result = AIResult(
            text="This reply must never be stored in telemetry",
            input_tokens=12,
            output_tokens=8,
            total_tokens=20,
            cost_usd=Decimal("0.0001"),
            cost_source="litellm_response_cost",
            actual_model="deepseek-flash",
        )

    @patch("app.services.usage_service.httpx.Client")
    def test_records_only_usage_metadata_and_uses_legacy_service_role_auth(self, client_class):
        client = client_class.return_value.__enter__.return_value
        settings = Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="eyJlegacy-service-role-token",
        )
        request_id = uuid4()

        record_ai_usage(
            settings,
            user_id="user-123",
            request_id=request_id,
            endpoint="chat",
            provider="deepseek",
            result=self.result,
        )

        kwargs = client.post.call_args.kwargs
        self.assertEqual(kwargs["json"], {
            "request_id": str(request_id),
            "user_id": "user-123",
            "endpoint": "chat",
            "provider": "deepseek",
            "model": "deepseek-flash",
            "input_tokens": 12,
            "output_tokens": 8,
            "total_tokens": 20,
            "cost_usd": "0.0001",
            "cost_source": "litellm_response_cost",
        })
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer eyJlegacy-service-role-token")
        self.assertEqual(kwargs["headers"]["apikey"], "eyJlegacy-service-role-token")
        self.assertNotIn(self.result.text, str(kwargs["json"]))

    @patch("app.services.usage_service.httpx.Client")
    def test_new_secret_key_is_sent_only_as_apikey(self, client_class):
        settings = Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="sb_secret_example",
        )

        record_ai_usage(
            settings,
            user_id="user-123",
            request_id=uuid4(),
            endpoint="prompts",
            provider="deepseek",
            result=self.result,
        )

        headers = client_class.return_value.__enter__.return_value.post.call_args.kwargs["headers"]
        self.assertEqual(headers["apikey"], "sb_secret_example")
        self.assertNotIn("Authorization", headers)

    @patch("app.services.usage_service.httpx.Client")
    def test_telemetry_failure_is_best_effort(self, client_class):
        client = client_class.return_value.__enter__.return_value
        client.post.side_effect = RuntimeError("private provider response")

        settings = Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="sb_secret_example",
        )
        record_ai_usage(
            settings,
            user_id="user-123",
            request_id=uuid4(),
            endpoint="chat",
            provider="deepseek",
            result=self.result,
        )


if __name__ == "__main__":
    unittest.main()
