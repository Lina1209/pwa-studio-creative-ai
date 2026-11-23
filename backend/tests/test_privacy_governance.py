from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user


USER = StudioUser(
    user_id="11111111-1111-4111-8111-111111111111",
    email="creator@example.test",
    role="creator",
)


def _client():
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app)


def test_privacy_consent_acceptance_is_blocked_until_policy_is_published(monkeypatch):
    import app.main as main

    calls = []
    monkeypatch.setattr(main.settings, "privacy_notice_version", "unpublished")
    monkeypatch.setattr(main, "record_consent_event", lambda *args, **kwargs: calls.append(kwargs))
    client = _client()
    try:
        response = client.post("/api/privacy/consent", json={
            "consent_scope": "privacy_notice", "action": "accepted",
        })
        assert response.status_code == 503
        assert calls == []
    finally:
        app.dependency_overrides.clear()


def test_privacy_consent_withdrawal_is_recorded_even_when_feature_is_disabled(monkeypatch):
    import app.main as main

    calls = []
    monkeypatch.setattr(main.settings, "privacy_notice_version", "unpublished")
    monkeypatch.setattr(main.settings, "vision_consent_version", "unpublished")
    monkeypatch.setattr(main, "record_consent_event", lambda *args, **kwargs: calls.append(kwargs) or "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    client = _client()
    try:
        response = client.post("/api/privacy/consent", json={
            "consent_scope": "vision_deepseek",
            "action": "withdrawn",
            "source": "account_settings",
        })
        assert response.status_code == 200
        assert response.json()["action"] == "withdrawn"
        assert calls[0]["user_id"] == UUID(USER.user_id)
        assert calls[0]["consent_scope"] == "vision_deepseek"
        assert calls[0]["source"] == "account_settings"
    finally:
        app.dependency_overrides.clear()


def test_privacy_consent_status_is_owner_scoped_and_not_cacheable(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "get_consent_status", lambda settings, user_id: [{
        "consent_scope": "vision_deepseek",
        "action": "withdrawn",
        "policy_version": "privacy-v1",
        "consent_version": "vision-v1",
        "occurred_at": "2026-11-23T12:00:00+00:00",
        "event_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    }])
    client = _client()
    try:
        response = client.get("/api/privacy/consent")
        assert response.status_code == 200
        assert response.json()[0]["action"] == "withdrawn"
        assert response.headers["cache-control"] == "private, no-store"
    finally:
        app.dependency_overrides.clear()


def test_privacy_request_submission_and_listing_are_owner_scoped(monkeypatch):
    import app.main as main

    calls = []
    monkeypatch.setattr(
        main, "create_privacy_request",
        lambda settings, **kwargs: calls.append(kwargs) or {
            "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "request_type": "export",
            "status": "submitted",
            "created_at": "2026-11-23T12:00:00+00:00",
            "duplicate": False,
        },
    )
    monkeypatch.setattr(
        main, "list_privacy_requests",
        lambda settings, **kwargs: [{
            "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            "request_type": "export",
            "status": "submitted",
            "created_at": "2026-11-23T12:00:00+00:00",
            "updated_at": "2026-11-23T12:00:00+00:00",
            "completed_at": None,
        }],
    )
    client = _client()
    try:
        response = client.post("/api/privacy/requests", json={
            "request_type": "export",
            "idempotency_key": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        })
        assert response.status_code == 200
        assert response.json()["status"] == "submitted"
        assert calls[0]["user_id"] == UUID(USER.user_id)
        listing = client.get("/api/privacy/requests")
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert listing.headers["cache-control"] == "private, no-store"
    finally:
        app.dependency_overrides.clear()


def test_privacy_request_schema_rejects_unknown_fields():
    client = _client()
    try:
        response = client.post("/api/privacy/requests", json={
            "request_type": "deletion",
            "idempotency_key": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "user_id": "22222222-2222-4222-8222-222222222222",
        })
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
