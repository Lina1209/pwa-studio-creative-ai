from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services import assistant_history_service as history


OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
CONVERSATION = "33333333-3333-4333-8333-333333333333"


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.content = b"[]" if payload is not None else b""
    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failed", request=request, response=response)
    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, parent_rows, inserted_rows=None):
        self.parent_rows = parent_rows
        self.inserted_rows = inserted_rows or []
        self.calls = []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def get(self, *args, **kwargs):
        self.calls.append(("get", args, kwargs))
        return FakeResponse(self.parent_rows)
    def post(self, *args, **kwargs):
        self.calls.append(("post", args, kwargs))
        return FakeResponse(self.inserted_rows)


def test_assistant_reply_write_checks_conversation_owner_before_insert(monkeypatch):
    client = FakeClient([{"id": CONVERSATION}], [{"id": "message-id", "role": "assistant"}])
    monkeypatch.setattr(history.httpx, "Client", lambda **kwargs: client)
    settings = Settings(supabase_url="https://project.supabase.co", supabase_service_role_key="sb_secret_test")

    result = history.save_assistant_reply(settings, OWNER, CONVERSATION, "A real server response")

    assert result["role"] == "assistant"
    assert [call[0] for call in client.calls] == ["get", "post"]
    params = client.calls[0][2]["params"]
    assert params["user_id"] == f"eq.{OWNER}"
    payload = client.calls[1][2]["json"]
    assert payload["user_id"] == OWNER
    assert payload["role"] == "assistant"


def test_foreign_or_missing_conversation_never_receives_assistant_insert(monkeypatch):
    client = FakeClient([])
    monkeypatch.setattr(history.httpx, "Client", lambda **kwargs: client)
    settings = Settings(supabase_url="https://project.supabase.co", supabase_service_role_key="sb_secret_test")

    with pytest.raises(HTTPException) as exc:
        history.save_assistant_reply(settings, OTHER, CONVERSATION, "Forged response")

    assert exc.value.status_code == 404
    assert [call[0] for call in client.calls] == ["get"]


def test_invalid_conversation_and_oversized_content_are_rejected():
    settings = Settings(supabase_url="https://project.supabase.co", supabase_service_role_key="sb_secret_test")
    with pytest.raises(HTTPException) as invalid:
        history.save_assistant_reply(settings, OWNER, "not-a-uuid", "Reply")
    assert invalid.value.status_code == 422
    with pytest.raises(HTTPException) as oversized:
        history.save_assistant_reply(settings, OWNER, CONVERSATION, "x" * 12001)
    assert oversized.value.status_code == 422
