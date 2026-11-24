from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services import admin_analytics_service


START = datetime.now(timezone.utc) - timedelta(days=7)
END = datetime.now(timezone.utc)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.supabase.co/rest/v1/rpc/admin_analytics_summary")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failed", request=request, response=response)

    def json(self):
        return self.payload


def test_admin_analytics_returns_only_aggregate_metrics(monkeypatch):
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append((url, json, headers, timeout))
        return FakeResponse({
            "registered_accounts": 12,
            "accounts_with_project_updates": 5,
            "accounts_with_successful_ai_usage": 3,
        })

    monkeypatch.setattr(admin_analytics_service.httpx, "post", fake_post)
    settings = Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="sb_secret_test")
    result = admin_analytics_service.get_admin_analytics_summary(
        settings, start_at=START, end_at=END
    )

    assert result["metrics"] == {
        "registered_accounts": 12,
        "accounts_with_project_updates": 5,
        "accounts_with_successful_ai_usage": 3,
    }
    assert result["data_quality"]["visitors_and_sessions_included"] is False
    assert result["data_quality"]["profile_completeness_verified"] is False
    assert "items" not in result
    assert "email" not in str(result)
    assert calls[0][0].endswith("/rpc/admin_analytics_summary")
    assert calls[0][1]["p_start_at"].endswith("+00:00")
    assert calls[0][2]["apikey"] == "sb_secret_test"
    assert "Authorization" not in calls[0][2]


def test_admin_analytics_requires_server_storage_configuration():
    settings = Settings(supabase_url="https://example.supabase.co")
    with pytest.raises(HTTPException) as error:
        admin_analytics_service.get_admin_analytics_summary(settings, start_at=START, end_at=END)
    assert error.value.status_code == 503


@pytest.mark.parametrize("start,end", [
    (END, START),
    (START - timedelta(days=30), END),
    (START.replace(tzinfo=None), END),
    (START, END + timedelta(days=1)),
])
def test_admin_analytics_rejects_invalid_or_unbounded_dates(start, end):
    settings = Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="sb_secret_test")
    with pytest.raises(HTTPException) as error:
        admin_analytics_service.get_admin_analytics_summary(settings, start_at=start, end_at=end)
    assert error.value.status_code == 422


def test_admin_analytics_sanitizes_missing_rpc(monkeypatch):
    def missing_rpc(*args, **kwargs):
        return FakeResponse({}, status_code=404)

    monkeypatch.setattr(admin_analytics_service.httpx, "post", missing_rpc)
    settings = Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="sb_secret_test")
    with pytest.raises(HTTPException) as error:
        admin_analytics_service.get_admin_analytics_summary(settings, start_at=START, end_at=END)
    assert error.value.status_code == 503
    assert "not installed" in error.value.detail
