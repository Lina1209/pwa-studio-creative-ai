from uuid import UUID
from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import StudioUser, get_current_user

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def client_for(user):
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_my_profile_uses_authenticated_user(monkeypatch):
    import app.api.profiles as api
    captured = {}
    monkeypatch.setattr(api, "get_my_profile", lambda settings, user_id:
                        captured.update(user_id=user_id) or {"username": "creator"})
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).get("/api/profiles/me")
    assert response.status_code == 200
    assert captured["user_id"] == UUID(OWNER)


def test_profile_update_does_not_accept_identity_or_avatar_url(monkeypatch):
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).patch(
        "/api/profiles/me", json={"username": "new_name", "id": OTHER, "avatar_url": "https://evil.test/x"})
    assert response.status_code == 422


def test_profile_update_validates_and_scopes_actor(monkeypatch):
    import app.api.profiles as api
    captured = {}
    monkeypatch.setattr(api, "update_my_profile", lambda settings, user_id, values:
                        captured.update(user_id=user_id, values=values) or {"username": "new_name"})
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).patch(
        "/api/profiles/me", json={"username": "New_Name", "bio": "hello"})
    assert response.status_code == 200
    assert captured == {"user_id": UUID(OWNER), "values": {"username": "New_Name", "bio": "hello"}}


def test_public_directory_only_returns_service_filtered_results(monkeypatch):
    import app.api.profiles as api
    captured = {}
    monkeypatch.setattr(api, "search_public_profiles", lambda settings, actor_id, query:
                        captured.update(actor=actor_id, query=query) or [{"username": "artist"}])
    response = client_for(StudioUser(user_id=OWNER, email=None, role="creator")).get(
        "/api/profiles/search?q=ar")
    assert response.status_code == 200
    assert captured == {"actor": UUID(OWNER), "query": "ar"}

