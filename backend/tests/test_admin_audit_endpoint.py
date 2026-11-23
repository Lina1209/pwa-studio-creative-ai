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
    import app.services.auth as auth_module

    denied_event = {}
    monkeypatch.setattr(auth_module, "record_admin_audit_event", lambda *a, **k: denied_event.update(k) or "audit-id")

    def forbidden(*args, **kwargs):
        raise AssertionError("audit journal must not be read by a creator")

    monkeypatch.setattr(main_module, "get_admin_audit_events", forbidden)
    client = _client_for(StudioUser(user_id="11111111-1111-4111-8111-111111111111", email=None, role="creator"))
    try:
        response = client.get("/api/admin/audit-events")
        assert response.status_code == 403
        assert response.json()["detail"] == "This operation is not permitted."
        assert denied_event["actor_user_id"] == UUID("11111111-1111-4111-8111-111111111111")
        assert denied_event["action"] == "admin.permission.denied"
        assert denied_event["outcome"] == "denied"
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
        response = client.get("/api/admin/audit-events?limit=1")
        assert response.status_code == 200
        assert response.json()["events"] == [event]
        assert response.json()["next_cursor"] == {
            "before": event["occurred_at"], "before_id": event["id"]
        }
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


def test_admin_audit_journal_rejects_incomplete_cursor():
    client = _client_for(StudioUser(user_id="22222222-2222-4222-8222-222222222222", email=None, role="admin"))
    try:
        response = client.get("/api/admin/audit-events?before_id=33333333-3333-4333-8333-333333333333")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_admin_audit_journal_rejects_timezone_free_cursor():
    client = _client_for(StudioUser(user_id="22222222-2222-4222-8222-222222222222", email=None, role="admin"))
    try:
        response = client.get("/api/admin/audit-events?before=2026-11-22T10:00:00&before_id=33333333-3333-4333-8333-333333333333")
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()



def test_admin_support_reply_records_a_specific_mutation_action(monkeypatch):
    import app.main as main_module

    actor = "22222222-2222-4222-8222-222222222222"
    ticket_id = UUID("33333333-3333-4333-8333-333333333333")
    captured = {}
    monkeypatch.setattr(main_module, "get_ticket", lambda *a, **k: {"id": str(ticket_id)})
    monkeypatch.setattr(main_module, "add_message", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: captured.update(k) or "audit-id")
    client = _client_for(StudioUser(user_id=actor, email=None, role="admin"))
    try:
        response = client.post(f"/api/admin/support/tickets/{ticket_id}/messages", json={"message": "Ответ поддержки"})
        assert response.status_code == 201
        assert captured["action"] == "admin.support.reply"
        assert captured["outcome"] == "executed"
        assert captured["resource_id"] == ticket_id
    finally:
        app.dependency_overrides.clear()


def test_admin_support_status_change_records_a_specific_mutation_action(monkeypatch):
    import app.main as main_module
    import app.services.support_inbox as support_module

    actor = "22222222-2222-4222-8222-222222222222"
    ticket_id = UUID("33333333-3333-4333-8333-333333333333")
    captured = {}
    monkeypatch.setattr(main_module, "get_ticket", lambda *a, **k: {"id": str(ticket_id)})
    monkeypatch.setattr(support_module, "update_ticket_status", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: captured.update(k) or "audit-id")
    client = _client_for(StudioUser(user_id=actor, email=None, role="admin"))
    try:
        response = client.patch(f"/api/admin/support/tickets/{ticket_id}/status", json={"status": "resolved"})
        assert response.status_code == 200
        assert captured["action"] == "admin.support.status.changed"
        assert captured["outcome"] == "executed"
        assert captured["resource_id"] == ticket_id
    finally:
        app.dependency_overrides.clear()
