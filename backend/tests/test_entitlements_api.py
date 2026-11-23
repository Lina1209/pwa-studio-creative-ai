from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


USER = "11111111-1111-4111-8111-111111111111"


def _client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_entitlements_endpoint_requires_authenticated_user():
    response = TestClient(app).get("/api/me/entitlements")
    assert response.status_code == 401


def test_entitlements_endpoint_returns_only_resolved_user_state(monkeypatch):
    import app.main as main

    captured = {}
    monkeypatch.setattr(
        main,
        "resolve_user_entitlements",
        lambda settings, *, user_id: captured.update(user_id=user_id) or {
            "status": "no_active_plan",
            "plan": None,
            "features": [],
            "quotas": {},
            "pending_assignment_exists": True,
            "capabilities_enabled": False,
        },
    )
    response = _client(StudioUser(user_id=USER, email=None, role="creator")).get(
        "/api/me/entitlements"
    )
    assert response.status_code == 200
    assert captured["user_id"].hex == USER.replace("-", "")
    body = response.json()
    assert body["status"] == "no_active_plan"
    assert body["capabilities_enabled"] is False
    assert body["pending_assignment_exists"] is True
    assert body["operational_admission_limits_are_separate"] is True
    assert response.headers["cache-control"] == "private, no-store"


def test_entitlements_endpoint_hides_storage_errors(monkeypatch):
    import app.main as main
    from app.services.entitlements import EntitlementsUnavailable

    monkeypatch.setattr(
        main,
        "resolve_user_entitlements",
        lambda *a, **k: (_ for _ in ()).throw(EntitlementsUnavailable("secret storage detail")),
    )
    response = _client(StudioUser(user_id=USER, email=None, role="creator")).get(
        "/api/me/entitlements"
    )
    assert response.status_code == 503
    assert "secret storage detail" not in response.text
