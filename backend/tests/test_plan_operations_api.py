from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user

ADMIN = "11111111-1111-4111-8111-111111111111"
CREATOR = "22222222-2222-4222-8222-222222222222"
DRAFT = "33333333-3333-4333-8333-333333333333"
APPROVED = "44444444-4444-4444-8444-444444444444"
TARGET = "55555555-5555-4555-8555-555555555555"
ASSIGNMENT = "66666666-6666-4666-8666-666666666666"


def _client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_creator_cannot_approve_plan_draft(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "approve_plan_draft", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    response = _client(StudioUser(user_id=CREATOR, email=None, role="creator")).post(
        f"/api/admin/plans/drafts/{DRAFT}/approve", json={"reason": "Reviewed and approved"}
    )
    assert response.status_code == 403


def test_admin_approval_uses_verified_actor_and_returns_inert_flags(monkeypatch):
    import app.main as main

    captured = {}
    audit_calls = []
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: audit_calls.append(k) or "audit-id")
    monkeypatch.setattr(
        main, "approve_plan_draft",
        lambda *a, **k: captured.update(kwargs=k) or {"approved_plan": {"id": APPROVED}, "replayed": False},
    )
    response = _client(StudioUser(user_id=ADMIN, email=None, role="admin")).post(
        f"/api/admin/plans/drafts/{DRAFT}/approve", json={"reason": "Reviewed and approved"}
    )
    assert response.status_code == 200
    assert captured["kwargs"]["actor_id"] == UUID(ADMIN)
    assert captured["kwargs"]["draft_id"] == UUID(DRAFT)
    assert audit_calls[0]["action"] == "admin.plan.draft.approve"
    assert audit_calls[0]["outcome"] == "requested"
    assert response.json()["activation_enabled"] is False
    assert response.json()["credits_granted"] is False
    assert response.json()["checkout_enabled"] is False


def test_creator_cannot_create_plan_assignment(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "create_pending_assignment", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    response = _client(StudioUser(user_id=CREATOR, email=None, role="creator")).post(
        "/api/admin/plans/assignments",
        headers={"Idempotency-Key": "test-assign-001"},
        json={
            "user_id": TARGET,
            "approved_plan_version_id": APPROVED,
            "source_reference": "manual-request-01",
            "starts_at": "2026-12-01T00:00:00Z",
            "ends_at": "2027-01-01T00:00:00Z",
            "reason": "Manual operator assignment",
        },
    )
    assert response.status_code == 403


def test_admin_assignment_is_pending_and_uses_verified_actor(monkeypatch):
    import app.main as main

    captured = {}
    audit_calls = []
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: audit_calls.append(k) or "audit-id")
    monkeypatch.setattr(
        main, "create_pending_assignment",
        lambda *a, **k: captured.update(kwargs=k) or {"assignment": {"id": ASSIGNMENT, "status": "pending"}, "replayed": False},
    )
    response = _client(StudioUser(user_id=ADMIN, email=None, role="admin")).post(
        "/api/admin/plans/assignments",
        headers={"Idempotency-Key": "test-assign-001"},
        json={
            "user_id": TARGET,
            "approved_plan_version_id": APPROVED,
            "source_reference": "manual-request-01",
            "starts_at": "2026-12-01T00:00:00Z",
            "ends_at": "2027-01-01T00:00:00Z",
            "reason": "Manual operator assignment",
        },
    )
    assert response.status_code == 201
    assert captured["kwargs"]["actor_id"] == UUID(ADMIN)
    assert captured["kwargs"]["user_id"] == UUID(TARGET)
    assert captured["kwargs"]["assignment_source"] == "operator_grant"
    assert audit_calls[0]["action"] == "admin.plan.assignment.create"
    assert audit_calls[0]["outcome"] == "requested"
    assert response.json()["assignment"]["status"] == "pending"
    assert response.json()["activation_enabled"] is False
    assert response.json()["credits_granted"] is False
    assert response.json()["checkout_enabled"] is False


def test_assignment_rejects_non_operator_source():
    response = _client(StudioUser(user_id=ADMIN, email=None, role="admin")).post(
        "/api/admin/plans/assignments",
        headers={"Idempotency-Key": "test-assign-001"},
        json={
            "user_id": TARGET,
            "approved_plan_version_id": APPROVED,
            "assignment_source": "verified_payment",
            "source_reference": "manual-request-01",
            "starts_at": "2026-12-01T00:00:00Z",
            "ends_at": "2027-01-01T00:00:00Z",
            "reason": "Manual operator assignment",
        },
    )
    assert response.status_code == 422


def test_assignment_rejects_timezone_free_dates(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "create_pending_assignment", lambda *a, **k: (_ for _ in ()).throw(ValueError("timezone")))
    response = _client(StudioUser(user_id=ADMIN, email=None, role="admin")).post(
        "/api/admin/plans/assignments",
        headers={"Idempotency-Key": "test-assign-001"},
        json={
            "user_id": TARGET,
            "approved_plan_version_id": APPROVED,
            "source_reference": "manual-request-01",
            "starts_at": "2026-12-01T00:00:00",
            "ends_at": "2027-01-01T00:00:00",
            "reason": "Manual operator assignment",
        },
    )
    assert response.status_code == 422


def test_plan_approval_fails_closed_when_intent_audit_is_unavailable(monkeypatch):
    import app.main as main
    from app.services.admin_audit_service import AdminAuditUnavailable

    mutations = []
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: (_ for _ in ()).throw(AdminAuditUnavailable("unavailable")))
    monkeypatch.setattr(main, "approve_plan_draft", lambda *a, **k: mutations.append(True))
    response = _client(StudioUser(user_id=ADMIN, email=None, role="admin")).post(
        f"/api/admin/plans/drafts/{DRAFT}/approve", json={"reason": "Reviewed and approved"}
    )
    assert response.status_code == 503
    assert mutations == []


def test_plan_assignment_fails_closed_when_intent_audit_is_unavailable(monkeypatch):
    import app.main as main
    from app.services.admin_audit_service import AdminAuditUnavailable

    mutations = []
    monkeypatch.setattr(main, "record_admin_audit_event", lambda *a, **k: (_ for _ in ()).throw(AdminAuditUnavailable("unavailable")))
    monkeypatch.setattr(main, "create_pending_assignment", lambda *a, **k: mutations.append(True))
    response = _client(StudioUser(user_id=ADMIN, email=None, role="admin")).post(
        "/api/admin/plans/assignments",
        headers={"Idempotency-Key": "test-assign-002"},
        json={
            "user_id": TARGET,
            "approved_plan_version_id": APPROVED,
            "source_reference": "manual-request-02",
            "starts_at": "2026-12-01T00:00:00Z",
            "ends_at": "2027-01-01T00:00:00Z",
            "reason": "Manual operator assignment",
        },
    )
    assert response.status_code == 503
    assert mutations == []
