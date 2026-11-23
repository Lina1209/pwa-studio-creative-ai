from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user
from app.services.admin_audit_service import AdminAuditUnavailable


def _client_for(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_admin_wallet_summary_requires_wallet_permission(monkeypatch):
    import app.main as main_module
    import app.services.auth as auth_module

    denied = {}
    monkeypatch.setattr(auth_module, "record_admin_audit_event", lambda *a, **k: denied.update(k) or "audit-id")
    monkeypatch.setattr(
        main_module, "get_credit_wallet_snapshot",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wallet data must not be read")),
    )
    client = _client_for(StudioUser(
        user_id="11111111-1111-4111-8111-111111111111", email=None, role="creator"
    ))
    try:
        response = client.get("/api/admin/financial/wallets/22222222-2222-4222-8222-222222222222")
        assert response.status_code == 403
        assert denied["action"] == "admin.permission.denied"
        assert denied["reason"] == "Denied capability: admin.finance.wallets.read"
    finally:
        app.dependency_overrides.clear()


def test_admin_wallet_summary_is_minimal_and_audited(monkeypatch):
    import app.main as main_module

    actor = "33333333-3333-4333-8333-333333333333"
    target = "44444444-4444-4444-8444-444444444444"
    monkeypatch.setattr(main_module, "get_credit_wallet_snapshot", lambda *a, **k: SimpleNamespace(
        user_id=UUID(target), available_credits=120, reserved_credits=15,
        holds=[{"id": "hold-1"}], lot_count=2, allocation_count=1,
    ))
    audit = {}
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: audit.update(k) or "audit-id")
    client = _client_for(StudioUser(user_id=actor, email=None, role="admin"))
    try:
        response = client.get(f"/api/admin/financial/wallets/{target}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json() == {
            "user_id": target, "currency_unit": "credit",
            "available_credits": 120, "reserved_credits": 15,
            "total_credits": 135, "active_holds_count": 1,
            "lot_count": 2, "allocation_count": 1,
        }
        assert audit["actor_user_id"] == UUID(actor)
        assert audit["action"] == "admin.user.view"
        assert audit["resource_type"] == "credit_wallet"
        assert audit["resource_id"] == UUID(target)
        assert "ledger" not in response.json()
    finally:
        app.dependency_overrides.clear()


def test_admin_wallet_summary_fails_closed_when_audit_write_fails(monkeypatch):
    import app.main as main_module

    target = "44444444-4444-4444-8444-444444444444"
    monkeypatch.setattr(main_module, "get_credit_wallet_snapshot", lambda *a, **k: SimpleNamespace(
        user_id=UUID(target), available_credits=120, reserved_credits=15,
        holds=[], lot_count=2, allocation_count=1,
    ))
    monkeypatch.setattr(
        main_module, "record_admin_audit_event",
        lambda *a, **k: (_ for _ in ()).throw(AdminAuditUnavailable("offline")),
    )
    client = _client_for(StudioUser(
        user_id="33333333-3333-4333-8333-333333333333", email=None, role="admin"
    ))
    try:
        response = client.get(f"/api/admin/financial/wallets/{target}")
        assert response.status_code == 503
        assert "available_credits" not in response.json()
    finally:
        app.dependency_overrides.clear()
