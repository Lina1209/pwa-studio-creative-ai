from fastapi.testclient import TestClient
from fastapi import HTTPException
from types import SimpleNamespace

from app import main
from app.core.config import Settings
from app.services.auth import StudioUser, get_current_user
from app.services import moderation_service


ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CREATOR_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TARGET_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def test_audit_log_service_applies_filters_stable_order_and_bounded_page(monkeypatch):
    captured = {}

    def fake_request(settings, method, table, *, params=None, payload=None):
        captured.update(method=method, table=table, params=params)
        return [{"id": 3}, {"id": 2}, {"id": 1}]

    monkeypatch.setattr(moderation_service, "_request", fake_request)
    result = moderation_service.list_admin_audit_log(
        Settings(), page=2, page_size=2,
        actor_user_id=ADMIN_ID, target_user_id=TARGET_ID,
        action="user.suspended", entity_type="suspension",
    )

    assert captured["method"] == "GET"
    assert captured["table"] == "admin_audit_log"
    assert captured["params"]["actor_user_id"] == f"eq.{ADMIN_ID}"
    assert captured["params"]["target_user_id"] == f"eq.{TARGET_ID}"
    assert captured["params"]["action"] == "eq.user.suspended"
    assert captured["params"]["entity_type"] == "eq.suspension"
    assert captured["params"]["order"] == "created_at.desc,id.desc"
    assert captured["params"]["offset"] == "2"
    assert captured["params"]["limit"] == "3"
    assert result == {"items": [{"id": 3}, {"id": 2}], "page": 2, "page_size": 2, "has_more": True}


def test_audit_log_service_rejects_invalid_user_filter_before_storage(monkeypatch):
    called = False

    def unexpected_request(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(moderation_service, "_request", unexpected_request)

    try:
        moderation_service.list_admin_audit_log(Settings(), actor_user_id="not-a-uuid")
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Expected invalid actor UUID to be rejected.")
    assert called is False


def test_audit_log_route_rejects_unauthenticated_request(monkeypatch):
    main.app.dependency_overrides.clear()
    settings = main.get_settings().model_copy(update={"supabase_url": "https://example.supabase.co"})
    monkeypatch.setattr("app.services.auth.get_settings", lambda: settings)
    with TestClient(main.app) as client:
        response = client.get("/api/admin/audit-log")
    main.app.dependency_overrides.clear()
    assert response.status_code == 401


def test_audit_log_route_rejects_creator_before_storage(monkeypatch):
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(CREATOR_ID, None, "creator")

    def unexpected(*args, **kwargs):
        raise AssertionError("Creator must not reach audit storage.")

    monkeypatch.setattr(main, "list_admin_audit_log", unexpected)
    with TestClient(main.app) as client:
        response = client.get("/api/admin/audit-log")
    main.app.dependency_overrides.clear()
    assert response.status_code == 403


def test_audit_log_route_returns_page_for_admin(monkeypatch):
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(ADMIN_ID, None, "admin")
    calls = []

    def fake_list(settings, **kwargs):
        calls.append(kwargs)
        return {"items": [{"id": 1, "action": "user.suspended"}],
                "page": kwargs["page"], "page_size": kwargs["page_size"], "has_more": False}

    monkeypatch.setattr(main, "list_admin_audit_log", fake_list)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/audit-log?page=3&page_size=25"
            f"&actor_user_id={ADMIN_ID}&target_user_id={TARGET_ID}"
            "&action=user.suspended&entity_type=suspension"
        )
    main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["page"] == 3
    assert response.json()["page_size"] == 25
    assert calls == [{
        "page": 3, "page_size": 25, "actor_user_id": ADMIN_ID,
        "target_user_id": TARGET_ID, "action": "user.suspended",
        "entity_type": "suspension",
    }]


def test_audit_log_route_validates_page_size_and_filter_format():
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(ADMIN_ID, None, "admin")
    with TestClient(main.app) as client:
        too_large = client.get("/api/admin/audit-log?page_size=1000")
        bad_action = client.get("/api/admin/audit-log?action=bad action")
        bad_uuid = client.get("/api/admin/audit-log?actor_user_id=not-a-uuid")
    main.app.dependency_overrides.clear()

    assert too_large.status_code == 422
    assert bad_action.status_code == 422
    assert bad_uuid.status_code == 422
