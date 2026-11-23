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
    audit = []
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: audit.append(k) or "audit-id")
    def grant(*a, **k):
        audit.append({"mutation": "grant"})
        captured.update(k)
        return UUID(ASSIGNMENT)
    monkeypatch.setattr(main_module, "grant_finance_role", grant)
    client = _client_for(StudioUser(user_id=ACTOR, email="ignored@example.test", role="admin"))
    try:
        response = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET,
            "role_code": "finance_operator",
            "scope_key": "tenant-a",
            "valid_until": "2027-01-01T00:00:00Z",
            "reason": "Support finance operations",
        })
        assert response.status_code == 200
        assert response.json() == {"assignment_id": ASSIGNMENT, "status": "granted"}
        assert captured["granted_by"] == UUID(ACTOR)
        assert captured["principal_id"] == UUID(TARGET)
        assert captured["role_code"] == "finance_operator"
        assert [item.get("outcome", item.get("mutation")) for item in audit] == ["requested", "grant", "executed"]
        assert audit[0]["action"] == audit[2]["action"] == "admin.finance.role.grant"
    finally:
        app.dependency_overrides.clear()


def test_finance_role_grant_rejects_extra_client_fields(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "grant_finance_role", lambda *a, **k: UUID(ASSIGNMENT))
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="admin"))
    try:
        response = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET, "role_code": "finance_operator",
            "scope_key": "tenant-a", "valid_until": "2027-01-01T00:00:00Z",
            "granted_by": TARGET, "reason": "Invalid client actor",
        })
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_finance_role_revoke_uses_verified_actor(monkeypatch):
    import app.main as main_module

    captured = {}
    audit = []
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: audit.append(k) or "audit-id")
    def revoke(*a, **k):
        audit.append({"mutation": "revoke"})
        captured.update(k)
        return UUID(ASSIGNMENT)
    monkeypatch.setattr(main_module, "revoke_finance_role", revoke)
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="admin"))
    try:
        response = client.post(f"/api/admin/finance/roles/{ASSIGNMENT}/revoke", json={
            "reason": "Assignment no longer required",
        })
        assert response.status_code == 200
        assert response.json() == {"revocation_id": ASSIGNMENT, "status": "revoked"}
        assert captured["revoked_by"] == UUID(ACTOR)
        assert captured["assignment_id"] == UUID(ASSIGNMENT)
        assert [item.get("outcome", item.get("mutation")) for item in audit] == ["requested", "revoke", "executed"]
        assert audit[0]["action"] == audit[2]["action"] == "admin.finance.role.revoke"
    finally:
        app.dependency_overrides.clear()



def test_finance_role_grant_duplicate_returns_conflict(monkeypatch):
    import app.main as main_module
    from app.services.finance_registry import FinanceRoleConflict

    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: "audit-id")
    monkeypatch.setattr(
        main_module, "grant_finance_role",
        lambda *a, **k: (_ for _ in ()).throw(FinanceRoleConflict("duplicate")),
    )
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="admin"))
    try:
        response = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET, "role_code": "finance_operator",
            "scope_key": "tenant-a", "valid_until": "2027-01-01T00:00:00Z",
            "reason": "Duplicate assignment",
        })
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()

def test_finance_role_grant_requires_explicit_scope_and_expiry(monkeypatch):
    import app.main as main_module

    called = []
    monkeypatch.setattr(main_module, "grant_finance_role", lambda *a, **k: called.append(k) or UUID(ASSIGNMENT))
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="admin"))
    try:
        missing_scope = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET, "role_code": "finance_operator",
            "valid_until": "2027-01-01T00:00:00Z", "reason": "Missing scope",
        })
        missing_expiry = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET, "role_code": "finance_operator",
            "scope_key": "tenant-a", "reason": "Missing expiry",
        })
        assert missing_scope.status_code == 422
        assert missing_expiry.status_code == 422
        assert called == []
    finally:
        app.dependency_overrides.clear()



def test_finance_role_grant_fails_closed_when_intent_audit_is_unavailable(monkeypatch):
    import app.main as main_module
    from app.services.admin_audit_service import AdminAuditUnavailable

    mutations = []
    monkeypatch.setattr(main_module, "record_admin_audit_event", lambda *a, **k: (_ for _ in ()).throw(AdminAuditUnavailable("unavailable")))
    monkeypatch.setattr(main_module, "grant_finance_role", lambda *a, **k: mutations.append("grant"))
    client = _client_for(StudioUser(user_id=ACTOR, email=None, role="admin"))
    try:
        response = client.post("/api/admin/finance/roles", json={
            "principal_id": TARGET, "role_code": "finance_operator",
            "scope_key": "tenant-a", "valid_until": "2027-01-01T00:00:00Z",
            "reason": "Must fail closed",
        })
        assert response.status_code == 503
        assert mutations == []
    finally:
        app.dependency_overrides.clear()
