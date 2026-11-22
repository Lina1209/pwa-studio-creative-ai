from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


def _client_for(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_admin_audit_journal_requires_admin(monkeypatch):
    import app.main as main_module

    def forbidden(*args, **kwargs):
        raise AssertionError("audit journal must not be read by a creator")

    monkeypatch.setattr(main_module, "get_admin_audit_events", forbidden)
    client = _client_for(StudioUser(user_id="11111111-1111-4111-8111-111111111111", email=None, role="creator"))
    try:
        response = client.get("/api/admin/audit-events")
        assert response.status_code == 403
        assert response.json()["detail"] == "This operation is not permitted."
    finally:
        app.dependency_overrides.clear()


def test_admin_audit_journal_returns_bounded_private_page(monkeypatch):
    import app.main as main_module

    actor = "22222222-2222-4222-8222-222222222222"
    event = {
        "id": "33333333-3333-4333-8333-333333333333",
        "occurred_at": "2026-11-23T00:00:00+00:00",
        "actor_user_id": actor, "action": "admin.access", "outcome": "allowed",
        "resource_type": "platform", "resource_id": None, "correlation_id": None,
        "reason": "Viewed administrative audit journal",
    }
    calls = {}
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: calls.update(k) or "audit-id")
    monkeypatch.setattr(main_module, "get_admin_audit_events", lambda *a, **k: [event])
    client = _client_for(StudioUser(user_id=actor, email=None, role="admin"))
    try:
        response = client.get("/api/admin/audit-events?limit=25")
        assert response.status_code == 200
        assert response.json()["events"] == [event]
        assert response.headers["cache-control"] == "private, no-store"
        assert calls["actor_user_id"] == UUID(actor)
        assert "service_role" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_admin_audit_journal_rejects_page_limit_over_200(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: "audit-id")
    monkeypatch.setattr(main_module, "get_admin_audit_events", lambda *a, **k: [])
    client = _client_for(StudioUser(user_id="22222222-2222-4222-8222-222222222222", email=None, role="admin"))
    try:
        response = client.get("/api/admin/audit-events?limit=201")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_admin_audit_journal_rejects_timezone_free_cursor():
    client = _client_for(StudioUser(user_id="22222222-2222-4222-8222-222222222222", email=None, role="admin"))
    try:
        response = client.get("/api/admin/audit-events?before=2026-11-22T10:00:00")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
