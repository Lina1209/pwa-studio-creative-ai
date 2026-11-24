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



def test_admin_ai_usage_is_bounded_and_summarizes_only_current_page(monkeypatch):
    class UsageResponse:
        content = b"[]"
        def raise_for_status(self): return None
        def json(self):
            return [
                {"request_id": "r1", "input_tokens": 10, "output_tokens": 5,
                 "total_tokens": 15, "cost_usd": "0.001", "provider": "deepseek"},
                {"request_id": "r2", "input_tokens": 20, "output_tokens": 7,
                 "total_tokens": 27, "cost_usd": None, "provider": "deepseek"},
                {"request_id": "r3", "input_tokens": 1, "output_tokens": 1,
                 "total_tokens": 2, "cost_usd": "0.5", "provider": "deepseek"},
            ]

    class UsageClient:
        def __init__(self, *, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, url, *, params, headers):
            self.url, self.params, self.headers = url, params, headers
            return UsageResponse()

    client = UsageClient(timeout=10.0)
    monkeypatch.setattr(usage_service.httpx, "Client", lambda timeout: client)
    result = usage_service.list_admin_ai_usage(
        Settings(supabase_url="https://example.supabase.co",
                 supabase_service_role_key="server-only"),
        page=2, page_size=2,
        user_id="00000000-0000-0000-0000-000000000001",
        provider="deepseek", endpoint="chat",
    )

    assert client.params["offset"] == "2"
    assert client.params["limit"] == "3"
    assert client.params["user_id"] == "eq.00000000-0000-0000-0000-000000000001"
    assert client.params["provider"] == "eq.deepseek"
    assert client.params["endpoint"] == "eq.chat"
    assert result["has_more"] is True
    assert result["summary_scope"] == "current_page"
    assert result["summary"]["requests"] == 2
    assert result["summary"]["total_tokens"] == 42
    assert result["summary"]["known_cost_usd"] == "0.001"
    assert result["summary"]["unknown_cost_requests"] == 1
    assert "prompt" not in client.params["select"]
    assert "response" not in client.params["select"]


def test_admin_ai_usage_requires_server_storage_credentials():
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as error:
        usage_service.list_admin_ai_usage(Settings(), page=1, page_size=10)
    assert error.value.status_code == 503



def test_durable_outbox_records_started_then_succeeded_without_private_content(monkeypatch):
    class OutboxClient(FakeClient):
        def __init__(self, *, timeout):
            super().__init__(timeout=timeout)
            self.patch_calls = []
        def patch(self, url, *, params, json, headers):
            self.patch_calls.append((url, params, json, headers))
            return FakeResponse()

    client = OutboxClient(timeout=8.0)
    monkeypatch.setattr(usage_service.httpx, "Client", lambda timeout: client)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="server-only",
    )
    request_id = uuid4()
    usage_service.begin_ai_usage_request(
        settings, user_id="00000000-0000-0000-0000-000000000001",
        request_id=request_id, endpoint="chat", provider="deepseek",
        model="deepseek-flash",
    )
    usage_service.complete_ai_usage_request(
        settings, request_id=request_id,
        result=_result(cost=Decimal("0.0000123"), cost_source="litellm_response_cost"),
    )

    start_url, start_payload, _ = client.calls[0]
    assert start_url.endswith("/rest/v1/ai_usage_outbox")
    assert start_payload["status"] == "started"
    assert start_payload["request_id"] == str(request_id)
    assert len(client.patch_calls) == 1
    url, params, payload, _ = client.patch_calls[0]
    assert url.endswith("/rest/v1/ai_usage_outbox")
    assert params == {"request_id": f"eq.{request_id}"}
    assert payload["status"] == "succeeded"
    assert payload["input_tokens"] == 17
    assert payload["output_tokens"] == 9
    assert payload["cost_usd"] == "0.0000123"
    assert "text" not in payload and "prompt" not in payload
    assert "This private response" not in repr(start_payload) + repr(payload)


def test_durable_outbox_fails_closed_before_provider_request_when_start_write_fails(monkeypatch):
    class FailingClient(FakeClient):
        def post(self, url, *, json, headers):
            raise RuntimeError("private content must not be logged")

    monkeypatch.setattr(usage_service.httpx, "Client", FailingClient)
    settings = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="server-only",
    )
    import pytest
    with pytest.raises(RuntimeError, match="provider call was not started"):
        usage_service.begin_ai_usage_request(
            settings, user_id="00000000-0000-0000-0000-000000000001",
            request_id=uuid4(), endpoint="prompts", provider="deepseek",
            model="deepseek-flash",
        )


def test_durable_outbox_marks_provider_failure_as_unknown_not_free(monkeypatch):
    class OutboxClient(FakeClient):
        def __init__(self, *, timeout):
            super().__init__(timeout=timeout)
            self.patch_calls = []
        def patch(self, url, *, params, json, headers):
            self.patch_calls.append((url, params, json, headers))
            return FakeResponse()

    client = OutboxClient(timeout=8.0)
    monkeypatch.setattr(usage_service.httpx, "Client", lambda timeout: client)
    usage_service.mark_ai_usage_unknown(
        Settings(supabase_url="https://example.supabase.co",
                 supabase_service_role_key="server-only"),
        request_id=uuid4(), error=TimeoutError("provider timeout"),
    )
    assert client.patch_calls[0][2]["status"] == "unknown"
    assert client.patch_calls[0][2]["error_type"] == "TimeoutError"
    assert "prompt" not in client.patch_calls[0][2]


def test_admin_outbox_reconciliation_is_read_only_bounded_and_keeps_unknown_cost_null(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import pytest
    from fastapi import HTTPException

    now = datetime.now(timezone.utc)
    stale_time = (now - timedelta(minutes=30)).isoformat()
    recent_time = (now - timedelta(minutes=2)).isoformat()
    class OutboxResponse:
        def raise_for_status(self): return None
        def json(self):
            return [
                {"request_id": "a", "user_id": "u1", "status": "started",
                 "started_at": stale_time, "cost_usd": None},
                {"request_id": "b", "user_id": "u2", "status": "unknown",
                 "started_at": recent_time, "cost_usd": "0.004"},
                {"request_id": "c", "user_id": "u3", "status": "unknown",
                 "started_at": recent_time, "cost_usd": None},
            ]
    class OutboxReadClient:
        def __init__(self, *, timeout): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, url, *, params, headers):
            self.url, self.params, self.headers = url, params, headers
            return OutboxResponse()

    client = OutboxReadClient(timeout=10.0)
    monkeypatch.setattr(usage_service.httpx, "Client", lambda timeout: client)
    result = usage_service.list_admin_ai_usage_reconciliation(
        Settings(supabase_url="https://example.supabase.co",
                 supabase_service_role_key="server-only"),
        page=1, page_size=2, stale_after_minutes=15,
    )
    assert client.url.endswith("/rest/v1/ai_usage_outbox")
    assert client.params["status"] == "in.(started,unknown)"
    assert client.params["limit"] == "3"
    assert result["has_more"] is True
    assert result["summary_scope"] == "current_page"
    assert result["summary"]["unresolved_requests"] == 2
    assert result["summary"]["started_requests"] == 1
    assert result["summary"]["unknown_requests"] == 1
    assert result["summary"]["known_cost_usd"] == "0.004"
    assert result["summary"]["unknown_cost_requests"] == 1
    assert result["summary"]["stale_started_requests"] == 1
    assert result["items"][0]["review_flag"] == "stale_started"
    assert result["automated_reconciliation"] is False
    assert "prompt" not in client.params["select"]
    assert "response" not in client.params["select"]
    assert not hasattr(client, "patch")
    assert not hasattr(client, "post")


def test_admin_outbox_reconciliation_requires_storage():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        usage_service.list_admin_ai_usage_reconciliation(Settings())
    assert error.value.status_code == 503
