from uuid import UUID
from fastapi.testclient import TestClient
from app.main import app
from app.services.auth import StudioUser, get_current_user
from app.services.admin_audit_service import AdminAuditUnavailable

TARGET = "44444444-4444-4444-8444-444444444444"
ACTOR = "33333333-3333-4333-8333-333333333333"

def client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)

def test_admin_credit_ledger_denies_non_admin_before_read(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "list_admin_credit_ledger", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not read")))
    c=client(StudioUser(user_id=ACTOR,email=None,role="creator"))
    try:
        assert c.get(f"/api/admin/financial/ledger/{TARGET}").status_code == 403
    finally: app.dependency_overrides.clear()

def test_admin_credit_ledger_is_audited_and_keyset_paginated(monkeypatch):
    import app.main as main
    entries=[{"entry_id": 17, "created_at":"2026-11-22T12:00:00+00:00"}]
    calls=[]; audits=[]
    monkeypatch.setattr(main,"list_admin_credit_ledger",lambda *a,**k: calls.append(k) or entries)
    monkeypatch.setattr(main,"record_admin_audit_event",lambda *a,**k: audits.append(k) or "audit-id")
    c=client(StudioUser(user_id=ACTOR,email=None,role="admin"))
    try:
        response=c.get(f"/api/admin/financial/ledger/{TARGET}",params={"limit":1})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json()["next_cursor"] == {"before_created_at":"2026-11-22T12:00:00+00:00","before_id":17}
        assert response.json()["unit"] == "credit"
        assert calls[0]["user_id"] == UUID(TARGET)
        assert audits[0]["resource_type"] == "credit_ledger"
        assert audits[0]["resource_id"] == UUID(TARGET)
    finally: app.dependency_overrides.clear()

def test_admin_credit_ledger_fails_closed_when_audit_unavailable(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,"list_admin_credit_ledger",lambda *a,**k: [{"entry_id":1}])
    monkeypatch.setattr(main,"record_admin_audit_event",lambda *a,**k: (_ for _ in ()).throw(AdminAuditUnavailable("offline")))
    c=client(StudioUser(user_id=ACTOR,email=None,role="admin"))
    try:
        response=c.get(f"/api/admin/financial/ledger/{TARGET}")
        assert response.status_code == 503
        assert "entries" not in response.json()
    finally: app.dependency_overrides.clear()

def test_admin_credit_ledger_rejects_partial_cursor():
    c=client(StudioUser(user_id=ACTOR,email=None,role="admin"))
    try:
        assert c.get(f"/api/admin/financial/ledger/{TARGET}",params={"before_id":5}).status_code == 422
    finally: app.dependency_overrides.clear()
