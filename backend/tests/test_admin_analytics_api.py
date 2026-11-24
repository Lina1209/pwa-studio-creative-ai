from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.auth import StudioUser, get_current_user


ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CREATOR_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture
def client():
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def _as_user(user_id, role):
    return lambda: StudioUser(user_id=user_id, email=None, role=role)


def test_admin_analytics_requires_authentication(client, monkeypatch):
    from app.services import auth
    from app.core.config import Settings

    monkeypatch.setattr(auth, "get_settings", lambda: Settings(supabase_url="https://example.supabase.co"))
    response = client.get("/api/admin/analytics?start_at=2026-11-17T00:00:00Z&end_at=2026-11-24T00:00:00Z")
    assert response.status_code == 401


def test_creator_cannot_access_admin_analytics(client, monkeypatch):
    main.app.dependency_overrides[get_current_user] = _as_user(CREATOR_ID, "creator")

    def unexpected(*args, **kwargs):
        raise AssertionError("Creator must not reach analytics storage.")

    monkeypatch.setattr(main, "get_admin_analytics_summary", unexpected)
    response = client.get("/api/admin/analytics?start_at=2026-11-17T00:00:00Z&end_at=2026-11-24T00:00:00Z")
    assert response.status_code == 403


def test_admin_analytics_returns_aggregate_summary(client, monkeypatch):
    main.app.dependency_overrides[get_current_user] = _as_user(ADMIN_ID, "admin")
    calls = []

    def fake_summary(settings, *, start_at, end_at):
        calls.append((start_at, end_at))
        return {"metrics": {"registered_accounts": 4}, "data_quality": {"scope": "aggregate_only"}}

    monkeypatch.setattr(main, "get_admin_analytics_summary", fake_summary)
    response = client.get("/api/admin/analytics?start_at=2026-11-17T00:00:00Z&end_at=2026-11-24T00:00:00Z")

    assert response.status_code == 200
    assert response.json()["metrics"]["registered_accounts"] == 4
    assert len(calls) == 1
    assert calls[0][0].tzinfo is not None
    assert calls[0][1].tzinfo is not None


@pytest.mark.parametrize("query", [
    "start_at=2026-11-24T00:00:00Z&end_at=2026-11-17T00:00:00Z",
    "start_at=2026-10-01T00:00:00Z&end_at=2026-11-24T00:00:00Z",
    "start_at=2026-11-17T00:00:00&end_at=2026-11-24T00:00:00Z",
])
def test_admin_analytics_rejects_invalid_ranges(client, query):
    main.app.dependency_overrides[get_current_user] = _as_user(ADMIN_ID, "admin")
    response = client.get("/api/admin/analytics?" + query)
    assert response.status_code == 422
