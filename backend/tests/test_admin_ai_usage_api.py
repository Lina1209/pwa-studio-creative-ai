from fastapi.testclient import TestClient

from app import main
from app.core.config import Settings
from app.services import auth
from app.services.auth import StudioUser, get_current_user


ADMIN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CREATOR_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_ai_usage_route_rejects_unauthenticated_request(monkeypatch):
    main.app.dependency_overrides.clear()
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(supabase_url="https://example.supabase.co"))
    with TestClient(main.app) as client:
        response = client.get("/api/admin/ai-usage")
    main.app.dependency_overrides.clear()
    assert response.status_code == 401


def test_ai_usage_route_rejects_creator_before_storage(monkeypatch):
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(CREATOR_ID, None, "creator")

    def unexpected(*args, **kwargs):
        raise AssertionError("Creator must not reach AI usage storage.")

    monkeypatch.setattr(main, "list_admin_ai_usage", unexpected)
    with TestClient(main.app) as client:
        response = client.get("/api/admin/ai-usage")
    main.app.dependency_overrides.clear()
    assert response.status_code == 403


def test_ai_usage_route_forwards_validated_filters_for_admin(monkeypatch):
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(ADMIN_ID, None, "admin")
    calls = []

    def fake_list(settings, **kwargs):
        calls.append(kwargs)
        return {"items": [], "page": kwargs["page"], "page_size": kwargs["page_size"],
                "has_more": False, "summary_scope": "current_page", "summary": {}}

    monkeypatch.setattr(main, "list_admin_ai_usage", fake_list)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/ai-usage?page=2&page_size=25"
            f"&user_id={CREATOR_ID}&provider=deepseek&endpoint=chat"
        )
    main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls == [{
        "page": 2, "page_size": 25, "user_id": CREATOR_ID,
        "provider": "deepseek", "endpoint": "chat",
    }]


def test_ai_usage_route_rejects_invalid_filters_and_page_size():
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(ADMIN_ID, None, "admin")
    with TestClient(main.app) as client:
        bad_uuid = client.get("/api/admin/ai-usage?user_id=not-a-uuid")
        bad_provider = client.get("/api/admin/ai-usage?provider=deepseek%20or%20true")
        bad_endpoint = client.get("/api/admin/ai-usage?endpoint=unknown")
        too_large = client.get("/api/admin/ai-usage?page_size=1000")
    main.app.dependency_overrides.clear()

    assert bad_uuid.status_code == 422
    assert bad_provider.status_code == 422
    assert bad_endpoint.status_code == 422
    assert too_large.status_code == 422


def test_reconciliation_route_rejects_unauthenticated_request(monkeypatch):
    main.app.dependency_overrides.clear()
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(supabase_url="https://example.supabase.co"))
    with TestClient(main.app) as client:
        response = client.get("/api/admin/ai-usage/reconciliation")
    main.app.dependency_overrides.clear()
    assert response.status_code == 401


def test_reconciliation_route_rejects_creator_before_storage(monkeypatch):
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(CREATOR_ID, None, "creator")

    def unexpected(*args, **kwargs):
        raise AssertionError("Creator must not reach reconciliation storage.")

    monkeypatch.setattr(main, "list_admin_ai_usage_reconciliation", unexpected)
    with TestClient(main.app) as client:
        response = client.get("/api/admin/ai-usage/reconciliation")
    main.app.dependency_overrides.clear()
    assert response.status_code == 403


def test_reconciliation_route_forwards_bounded_parameters_for_admin(monkeypatch):
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(ADMIN_ID, None, "admin")
    calls = []

    def fake_list(settings, **kwargs):
        calls.append(kwargs)
        return {"items": [], "page": kwargs["page"], "page_size": kwargs["page_size"],
                "has_more": False, "summary_scope": "current_page", "summary": {},
                "automated_reconciliation": False}

    monkeypatch.setattr(main, "list_admin_ai_usage_reconciliation", fake_list)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/admin/ai-usage/reconciliation?page=3&page_size=20"
            "&status=unknown&stale_after_minutes=45"
        )
    main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls == [{
        "page": 3, "page_size": 20, "status": "unknown",
        "stale_after_minutes": 45,
    }]


def test_reconciliation_route_rejects_invalid_status_and_unbounded_values():
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides[get_current_user] = lambda: StudioUser(ADMIN_ID, None, "admin")
    with TestClient(main.app) as client:
        bad_status = client.get("/api/admin/ai-usage/reconciliation?status=succeeded")
        oversized_page = client.get("/api/admin/ai-usage/reconciliation?page_size=1000")
        invalid_age = client.get("/api/admin/ai-usage/reconciliation?stale_after_minutes=99999")
    main.app.dependency_overrides.clear()

    assert bad_status.status_code == 422
    assert oversized_page.status_code == 422
    assert invalid_age.status_code == 422
