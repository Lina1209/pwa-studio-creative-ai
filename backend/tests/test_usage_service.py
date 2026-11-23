from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.core.config import Settings
from app.services.ai_service import AIResult
from app.services import usage_service


class FakeResponse:
    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self, *, timeout):
        self.timeout = timeout
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, json, headers):
        self.calls.append((url, json, headers))
        return FakeResponse()


def _result(*, cost=None, cost_source=None):
    return AIResult(
        text="This private response must never be persisted.",
        input_tokens=17,
        output_tokens=9,
        total_tokens=26,
        cost_usd=cost,
        cost_source=cost_source,
        actual_model="deepseek-flash",
    )


def test_record_ai_usage_persists_only_measured_metadata(monkeypatch):
    fake_client = FakeClient(timeout=5.0)
    monkeypatch.setattr(usage_service.httpx, "Client", lambda timeout: fake_client)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_test_only",
    )
    request_id = uuid4()

    usage_service.record_ai_usage(
        settings,
        user_id="00000000-0000-0000-0000-000000000001",
        request_id=request_id,
        endpoint="chat",
        provider="deepseek",
        result=_result(cost=Decimal("0.0000123"), cost_source="litellm_response_cost"),
    )

    assert len(fake_client.calls) == 1
    url, payload, headers = fake_client.calls[0]
    assert url == "https://example.supabase.co/rest/v1/ai_usage"
    assert payload == {
        "request_id": str(request_id),
        "user_id": "00000000-0000-0000-0000-000000000001",
        "endpoint": "chat",
        "provider": "deepseek",
        "model": "deepseek-flash",
        "input_tokens": 17,
        "output_tokens": 9,
        "total_tokens": 26,
        "cost_usd": "0.0000123",
        "cost_source": "litellm_response_cost",
    }
    assert headers["apikey"] == "sb_secret_test_only"
    assert headers["Prefer"] == "return=minimal"
    assert "text" not in payload
    assert "prompt" not in payload
    assert "This private response" not in repr(payload)


def test_record_ai_usage_keeps_unknown_cost_null(monkeypatch):
    fake_client = FakeClient(timeout=5.0)
    monkeypatch.setattr(usage_service.httpx, "Client", lambda timeout: fake_client)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_test_only",
    )

    usage_service.record_ai_usage(
        settings,
        user_id="00000000-0000-0000-0000-000000000001",
        request_id=uuid4(),
        endpoint="prompts",
        provider="deepseek",
        result=_result(),
    )

    payload = fake_client.calls[0][1]
    assert payload["cost_usd"] is None
    assert payload["cost_source"] is None


def test_record_ai_usage_failure_is_best_effort_and_does_not_leak_payload(monkeypatch, caplog):
    class FailingClient(FakeClient):
        def post(self, url, *, json, headers):
            raise RuntimeError("private prompt and provider payload must not appear in logs")

    monkeypatch.setattr(usage_service.httpx, "Client", FailingClient)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_test_only",
    )

    usage_service.record_ai_usage(
        settings,
        user_id="00000000-0000-0000-0000-000000000001",
        request_id=uuid4(),
        endpoint="chat",
        provider="deepseek",
        result=_result(),
    )

    assert "telemetry write failed" in caplog.text
    assert "private prompt" not in caplog.text
    assert "sb_secret_test_only" not in caplog.text


def test_record_ai_usage_skips_without_server_credentials(monkeypatch):
    def unexpected_client(*args, **kwargs):
        raise AssertionError("HTTP client must not be created without credentials")

    monkeypatch.setattr(usage_service.httpx, "Client", unexpected_client)
    usage_service.record_ai_usage(
        Settings(),
        user_id="00000000-0000-0000-0000-000000000001",
        request_id=uuid4(),
        endpoint="chat",
        provider="deepseek",
        result=_result(),
    )
