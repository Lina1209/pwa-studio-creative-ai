import httpx
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services import ai_rate_limit_service


def test_ai_rate_limit_returns_boolean_from_rpc(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return True

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    monkeypatch.setattr(ai_rate_limit_service.httpx, "post", fake_post)
    settings = Settings(supabase_url="https://example.supabase.co",
                        supabase_service_role_key="sb_secret_test")
    assert ai_rate_limit_service.consume_ai_request(
        settings, user_id="11111111-1111-4111-8111-111111111111", endpoint="chat"
    ) is True
    assert seen["url"].endswith("/rest/v1/rpc/consume_ai_rate_limit")
    assert seen["json"]["p_limit"] == 10
    assert seen["json"]["p_window_seconds"] == 60
    assert "Authorization" not in seen["headers"]


def test_ai_rate_limit_rejects_non_boolean_rpc_response(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"allowed": True}

    monkeypatch.setattr(ai_rate_limit_service.httpx, "post", lambda *a, **k: Response())
    settings = Settings(supabase_url="https://example.supabase.co",
                        supabase_service_role_key="sb_secret_test")
    with pytest.raises(HTTPException) as exc:
        ai_rate_limit_service.consume_ai_request(
            settings, user_id="11111111-1111-4111-8111-111111111111", endpoint="chat"
        )
    assert exc.value.status_code == 503


def test_ai_rate_limit_fails_closed_without_storage_configuration():
    with pytest.raises(HTTPException) as exc:
        ai_rate_limit_service.consume_ai_request(
            Settings(), user_id="11111111-1111-4111-8111-111111111111", endpoint="chat"
        )
    assert exc.value.status_code == 503


def test_ai_rate_limit_fails_closed_on_network_error(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(ai_rate_limit_service.httpx, "post", fail)
    settings = Settings(supabase_url="https://example.supabase.co",
                        supabase_service_role_key="sb_secret_test")
    with pytest.raises(HTTPException) as exc:
        ai_rate_limit_service.consume_ai_request(
            settings, user_id="11111111-1111-4111-8111-111111111111", endpoint="prompts"
        )
    assert exc.value.status_code == 503
