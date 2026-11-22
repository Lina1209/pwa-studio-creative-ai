from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


ACTOR = "11111111-1111-4111-8111-111111111111"
TARGET = "22222222-2222-4222-8222-222222222222"
ASSIGNMENT = "33333333-3333-4333-8333-333333333333"


def _client_for(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_finance_role_registry_endpoints_require_explicit_owner_permission(monkeypatch):
    import app.main as main_module
    import app.services.auth as auth_module

    denied = {}
    monkeypatch.setattr(auth_module, "record_admin_audit_event", lambda *a, **k: denied.update(k) or "audit")
    monkeypatch.setattr(main_module, "list_active_finance_roles", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not read registry")))
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="creator"))
    try:
        response = client.get(f"/api/admin/finance/roles/{TARGET}")
        assert response.status_code == 403
        assert denied["reason"] == "Denied capability: admin.finance.roles.manage"
    finally:
        app.dependency_overrides.clear()


def test_finance_role_grant_uses_verified_actor_and_audited_registry_rpc(monkeypatch):
    import app.main as main_module

    captured = {}
    monkeypatch.setattr(main_module, "grant_finance_role", lambda *a, **k: captured.update(k) or UUID(ASSIGNMENT))
    client = _client_for(StudioUser(user_id=ACTOR, email="ignored@example.test", role="admin"))
    try:
        response = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET,
            "role_code": "finance_operator",
            "scope_key": "tenant-a",
            "reason": "Support finance operations",
        })
        assert response.status_code == 200
        assert response.json() == {"assignment_id": ASSIGNMENT, "status": "granted"}
        assert captured["granted_by"] == UUID(ACTOR)
        assert captured["principal_id"] == UUID(TARGET)
        assert captured["role_code"] == "finance_operator"
    finally:
        app.dependency_overrides.clear()


def test_finance_role_grant_rejects_extra_client_fields(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "grant_finance_role", lambda *a, **k: UUID(ASSIGNMENT))
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="admin"))
    try:
        response = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET, "role_code": "finance_operator",
            "granted_by": TARGET, "reason": "Invalid client actor",
        })
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_finance_role_revoke_uses_verified_actor(monkeypatch):
    import app.main as main_module

    captured = {}
    monkeypatch.setattr(main_module, "revoke_finance_role", lambda *a, **k: captured.update(k) or UUID(ASSIGNMENT))
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="admin"))
    try:
        response = client.post(f"/api/admin/finance/roles/{ASSIGNMENT}/revoke", json={
            "reason": "Assignment no longer required",
        })
        assert response.status_code == 200
        assert response.json() == {"revocation_id": ASSIGNMENT, "status": "revoked"}
        assert captured["revoked_by"] == UUID(ACTOR)
        assert captured["assignment_id"] == UUID(ASSIGNMENT)
    finally:
        app.dependency_overrides.clear()



def test_finance_role_grant_duplicate_returns_conflict(monkeypatch):
    import app.main as main_module
    from app.services.finance_registry import FinanceRoleConflict

    monkeypatch.setattr(
        main_module, "grant_finance_role",
        lambda *a, **k: (_ for _ in ()).throw(FinanceRoleConflict("duplicate")),
    )
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="admin"))
    try:
        response = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET, "role_code": "finance_operator",
            "reason": "Duplicate assignment",
        })
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()
