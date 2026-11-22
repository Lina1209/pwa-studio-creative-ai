from decimal import Decimal
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


ACTOR = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")
REQUEST = UUID("33333333-3333-4333-8333-333333333333")
IDEMPOTENCY = UUID("44444444-4444-4444-8444-444444444444")


def _client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _grant(actor, permissions, scope):
    return SimpleNamespace(
        principal_id=actor, permissions=frozenset(permissions), active=True,
        scope_ids=frozenset({scope}),
        permission_scopes={p: frozenset({scope}) for p in permissions},
        global_permissions=frozenset(),
    )


def test_create_finance_request_uses_verified_actor_and_exact_permission_scope(monkeypatch):
    import app.main as main_module

    captured = {}
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(
        ACTOR, {"credit.compensation.request"}, f"user:{OTHER}"
    ))
    monkeypatch.setattr(main_module, "create_finance_operation_request", lambda *a, **k: captured.update(k) or REQUEST)
    monkeypatch.setattr(main_module, "read_finance_operation_request", lambda *a, **k: {
        "request_id": REQUEST, "requester_id": ACTOR,
        "request_type": "credit_compensation", "target_user_id": OTHER,
        "amount": Decimal("12"), "currency_code": "CRD",
        "scope_key": f"user:{OTHER}", "status": "pending",
    })
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.post("/api/finance/requests", json={
            "request_type": "credit_compensation", "target_user_id": str(OTHER),
            "amount": "12", "currency_code": "CRD",
            "reason": "Support case", "idempotency_key": str(IDEMPOTENCY),
        })
        assert response.status_code == 201
        assert response.json() == {
            "request_id": str(REQUEST), "status": "pending", "execution_enabled": False
        }
        assert captured["requester_id"] == ACTOR
        assert captured["target_user_id"] == OTHER
        assert captured["scope_key"] == f"user:{OTHER}"
    finally:
        app.dependency_overrides.clear()


def test_finance_request_rejects_missing_delegated_permission(monkeypatch):
    import app.main as main_module

    called = []
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(ACTOR, set(), f"user:{OTHER}"))
    monkeypatch.setattr(main_module, "create_finance_operation_request", lambda *a, **k: called.append(True))
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.post("/api/finance/requests", json={
            "request_type": "credit_compensation", "target_user_id": str(OTHER),
            "amount": "2", "currency_code": "CRD",
            "reason": "Support case", "idempotency_key": str(IDEMPOTENCY),
        })
        assert response.status_code == 403
        assert called == []
    finally:
        app.dependency_overrides.clear()


def test_finance_decision_rejects_self_approval_before_rpc(monkeypatch):
    import app.main as main_module

    called = []
    monkeypatch.setattr(main_module, "read_finance_operation_request", lambda *a, **k: {
        "request_id": REQUEST, "requester_id": ACTOR,
        "request_type": "credit_compensation", "target_user_id": OTHER,
        "amount": Decimal("1"), "currency_code": "CRD",
        "scope_key": f"user:{OTHER}", "status": "pending",
    })
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(
        ACTOR, {"credit.compensation.approve"}, f"user:{OTHER}"
    ))
    monkeypatch.setattr(main_module, "decide_finance_operation_request", lambda *a, **k: called.append(True))
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.post(f"/api/finance/requests/{REQUEST}/decision", json={
            "decision": "approve", "reason": "Self approval attempt",
        })
        assert response.status_code == 403
        assert called == []
    finally:
        app.dependency_overrides.clear()


def test_approval_checks_approver_role_and_server_actor(monkeypatch):
    import app.main as main_module

    captured = {}
    monkeypatch.setattr(main_module, "read_finance_operation_request", lambda *a, **k: {
        "request_id": REQUEST, "requester_id": OTHER,
        "request_type": "credit_compensation", "target_user_id": ACTOR,
        "amount": Decimal("1"), "currency_code": "CRD",
        "scope_key": f"user:{ACTOR}", "status": "pending",
    })
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(
        ACTOR, {"credit.compensation.approve"}, f"user:{ACTOR}"
    ))
    monkeypatch.setattr(main_module, "decide_finance_operation_request", lambda *a, **k: captured.update(k) or REQUEST)
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.post(f"/api/finance/requests/{REQUEST}/decision", json={
            "decision": "reject", "reason": "Not eligible",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        assert captured["actor_id"] == ACTOR
        assert captured["decision"] == "reject"
    finally:
        app.dependency_overrides.clear()


def test_cancel_is_limited_to_requester_and_its_scope(monkeypatch):
    import app.main as main_module

    captured = {}
    monkeypatch.setattr(main_module, "read_finance_operation_request", lambda *a, **k: {
        "request_id": REQUEST, "requester_id": ACTOR,
        "request_type": "billing_refund", "target_user_id": OTHER,
        "amount": Decimal("1"), "currency_code": "USD",
        "scope_key": f"user:{OTHER}", "status": "pending",
    })
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(
        ACTOR, {"billing.refund.cancel"}, f"user:{OTHER}"
    ))
    monkeypatch.setattr(main_module, "cancel_finance_operation_request", lambda *a, **k: captured.update(k) or REQUEST)
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.post(f"/api/finance/requests/{REQUEST}/cancel", json={
            "reason": "Requester withdrew request",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert captured["actor_id"] == ACTOR
    finally:
        app.dependency_overrides.clear()


def test_request_schema_rejects_client_actor_fields(monkeypatch):
    import app.main as main_module

    called = []
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(
        ACTOR, {"credit.compensation.request"}, f"user:{OTHER}"
    ))
    monkeypatch.setattr(main_module, "create_finance_operation_request", lambda *a, **k: called.append(True))
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.post("/api/finance/requests", json={
            "requester_id": str(OTHER), "request_type": "credit_compensation",
            "target_user_id": str(OTHER), "amount": "1", "currency_code": "CRD",
            "reason": "Forged actor",
            "idempotency_key": str(IDEMPOTENCY),
        })
        assert response.status_code == 422
        assert called == []
    finally:
        app.dependency_overrides.clear()



def test_finance_queue_returns_only_delegated_scopes_with_keyset_cursor(monkeypatch):
    import app.main as main_module

    captured = {}
    requested_at = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    rows = [{
        "request_id": REQUEST, "requester_id": OTHER,
        "request_type": "credit_compensation", "target_user_id": OTHER,
        "amount": Decimal("12"), "currency_code": "CRD",
        "scope_key": f"user:{OTHER}", "reason": "Approved support correction",
        "status": "pending", "requested_at": requested_at,
        "decided_by": None, "decided_at": None, "decision_reason": None,
        "cancelled_at": None,
    }, {
        "request_id": UUID("55555555-5555-4555-8555-555555555555"),
        "requester_id": OTHER, "request_type": "credit_compensation",
        "target_user_id": OTHER, "amount": Decimal("3"), "currency_code": "CRD",
        "scope_key": f"user:{OTHER}", "reason": "Second page item",
        "status": "pending", "requested_at": datetime(2026, 11, 22, tzinfo=timezone.utc),
        "decided_by": None, "decided_at": None, "decision_reason": None,
        "cancelled_at": None,
    }]
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(
        ACTOR, {"credit.compensation.read"}, f"user:{OTHER}"
    ))
    monkeypatch.setattr(
        main_module, "list_finance_operation_requests",
        lambda *a, **k: captured.update(k) or rows,
    )
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.get("/api/finance/requests?limit=1&status=pending")
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["request_id"] == str(REQUEST)
        assert body["next_cursor"] == {
            "before": requested_at.isoformat(),
            "before_id": str(REQUEST),
        }
        assert body["execution_enabled"] is False
        assert captured["credit_scope_keys"] == [f"user:{OTHER}"]
        assert captured["billing_scope_keys"] == []
        assert captured["limit"] == 2
        assert response.headers["cache-control"] == "private, no-store"
    finally:
        app.dependency_overrides.clear()


def test_finance_queue_denies_users_without_read_scope(monkeypatch):
    import app.main as main_module

    called = []
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(ACTOR, set(), f"user:{OTHER}"))
    monkeypatch.setattr(main_module, "list_finance_operation_requests", lambda *a, **k: called.append(True))
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.get("/api/finance/requests")
        assert response.status_code == 403
        assert called == []
    finally:
        app.dependency_overrides.clear()


def test_finance_queue_rejects_partial_cursor(monkeypatch):
    import app.main as main_module

    called = []
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: _grant(
        ACTOR, {"credit.compensation.read"}, f"user:{OTHER}"
    ))
    monkeypatch.setattr(main_module, "list_finance_operation_requests", lambda *a, **k: called.append(True))
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.get("/api/finance/requests?before=2026-11-23T12:00:00Z")
        assert response.status_code == 422
        assert called == []
    finally:
        app.dependency_overrides.clear()



def test_finance_profile_exposes_only_callers_own_capabilities(monkeypatch):
    import app.main as main_module

    grant = _grant(ACTOR, {
        "credit.compensation.read", "credit.compensation.request",
    }, f"user:{OTHER}")
    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: grant)
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.get("/api/finance/me")
        assert response.status_code == 200
        assert response.json() == {
            "active": True,
            "permissions": ["credit.compensation.read", "credit.compensation.request"],
            "scope_count": 1,
            "can_read_credit_requests": True,
            "can_read_refund_requests": False,
        }
        assert response.headers["cache-control"] == "private, no-store"
        assert str(OTHER) not in response.text
    finally:
        app.dependency_overrides.clear()


def test_finance_profile_returns_inactive_without_grants(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "resolve_finance_grant", lambda *a, **k: None)
    client = _client(StudioUser(user_id=str(ACTOR), email=None, role="creator"))
    try:
        response = client.get("/api/finance/me")
        assert response.status_code == 200
        assert response.json() == {"active": False, "permissions": [], "scope_count": 0}
    finally:
        app.dependency_overrides.clear()
