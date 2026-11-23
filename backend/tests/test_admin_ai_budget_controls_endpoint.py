from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


ADMIN = StudioUser(user_id="22222222-2222-4222-8222-222222222222", email="owner@example.com", role="admin")
CREATOR = StudioUser(user_id="33333333-3333-4333-8333-333333333333", email="creator@example.com", role="creator")


def _client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_global_budget_update_requires_admin_and_audit(monkeypatch):
    import app.main as main
    calls = []
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: calls.append(("audit", k)) or "event")
    monkeypatch.setattr(main, "update_global_budget", lambda *a, **k: calls.append(("rpc", k)) or {"enabled": True})
    client = _client(ADMIN)
    try:
        response = client.put("/api/admin/ai/budget/global", json={
            "enabled": True, "daily_budget_usd": "3.00", "max_outstanding_usd": "0.75"
        })
        assert response.status_code == 200
        assert [call[0] for call in calls] == ["audit", "rpc"]
        assert calls[0][1]["outcome"] == "requested"
    finally:
        app.dependency_overrides.clear()


def test_global_budget_rejects_outstanding_above_daily(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: "event")
    client = _client(ADMIN)
    try:
        response = client.put("/api/admin/ai/budget/global", json={
            "enabled": True, "daily_budget_usd": "1", "max_outstanding_usd": "2"
        })
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_provider_budget_denies_non_admin_before_rpc(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "update_provider_budget", lambda *a, **k: pytest.fail("RPC must not run"))
    client = _client(CREATOR)
    try:
        response = client.put("/api/admin/ai/budget/provider", json={
            "provider": "deepseek", "enabled": True, "daily_budget_usd": "1.5"
        })
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_unknown_reservation_requires_note_and_admin(monkeypatch):
    import app.main as main
    calls = []
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: calls.append("audit") or "event")
    monkeypatch.setattr(main, "resolve_unknown_reservation", lambda *a, **k: calls.append("resolve") or True)
    client = _client(ADMIN)
    try:
        bad = client.post("/api/admin/ai/budget/reservations/resolve", json={
            "request_id": "44444444-4444-4444-8444-444444444444",
            "resolution": "confirm_no_charge", "actual_estimated_cost_usd": None, "note": "short"
        })
        assert bad.status_code == 422
        good = client.post("/api/admin/ai/budget/reservations/resolve", json={
            "request_id": "44444444-4444-4444-8444-444444444444",
            "resolution": "confirm_no_charge", "actual_estimated_cost_usd": None,
            "note": "Provider confirmed no charge"
        })
        assert good.status_code == 200
        assert calls == ["audit", "resolve"]
    finally:
        app.dependency_overrides.clear()


def test_budget_change_fails_closed_when_audit_is_unavailable(monkeypatch):
    import app.main as main
    from app.services.admin_audit_service import AdminAuditUnavailable
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: (_ for _ in ()).throw(AdminAuditUnavailable()))
    monkeypatch.setattr(main, "update_global_budget", lambda *a, **k: pytest.fail("Budget RPC must not run without audit"))
    client = _client(ADMIN)
    try:
        response = client.put("/api/admin/ai/budget/global", json={
            "enabled": True, "daily_budget_usd": "3", "max_outstanding_usd": "1"
        })
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_provider_budget_rejects_gemini_for_admin(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: "event")
    monkeypatch.setattr(main, "update_provider_budget", lambda *a, **k: (_ for _ in ()).throw(ValueError("unsupported_ai_provider")))
    client = _client(ADMIN)
    try:
        response = client.put("/api/admin/ai/budget/provider", json={
            "provider": "gemini", "enabled": True, "daily_budget_usd": "1.5"
        })
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "path", "payload", "rpc_name"),
    [
        ("put", "/api/admin/ai/budget/global", {
            "enabled": True, "daily_budget_usd": "3", "max_outstanding_usd": "1"
        }, "update_global_budget"),
        ("put", "/api/admin/ai/budget/provider", {
            "provider": "deepseek", "enabled": True, "daily_budget_usd": "1"
        }, "update_provider_budget"),
        ("post", "/api/admin/ai/budget/reservations/resolve", {
            "request_id": "44444444-4444-4444-8444-444444444444",
            "resolution": "confirm_no_charge", "actual_estimated_cost_usd": None,
            "note": "Provider confirmed no charge"
        }, "resolve_unknown_reservation"),
    ],
)
def test_ai_budget_mutations_require_dedicated_capability(
    monkeypatch, method, path, payload, rpc_name
):
    import app.main as main
    import app.services.auth as auth

    monkeypatch.setattr(
        auth, "OWNER_CAPABILITIES",
        frozenset(set(auth.OWNER_CAPABILITIES) - {"admin.ai.budget.manage"}),
    )
    monkeypatch.setattr(
        auth, "record_admin_audit_event",
        lambda *a, **k: "denial-audit",
    )
    monkeypatch.setattr(
        main, rpc_name,
        lambda *a, **k: pytest.fail("AI budget mutation RPC must not run"),
    )
    client = _client(ADMIN)
    try:
        response = getattr(client, method)(path, json=payload)
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
