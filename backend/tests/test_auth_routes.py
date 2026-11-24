import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.auth import StudioUser, get_current_user


OWNER_ID = "11111111-1111-4111-8111-111111111111"
CREATOR_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def client():
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def as_user(user_id: str, email: str | None, role: str):
    return lambda: StudioUser(user_id=user_id, email=email, role=role)


def test_auth_me_requires_authentication(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_auth_me_returns_only_verified_user_identity(client):
    main.app.dependency_overrides[get_current_user] = as_user(
        CREATOR_ID, "creator@example.com", "creator"
    )

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": CREATOR_ID,
        "email": "creator@example.com",
        "role": "creator",
    }


def test_admin_me_rejects_creator(client):
    main.app.dependency_overrides[get_current_user] = as_user(
        CREATOR_ID, "creator@example.com", "creator"
    )

    response = client.get("/api/admin/me")

    assert response.status_code == 403


def test_admin_me_requires_authentication(client):
    response = client.get("/api/admin/me")

    assert response.status_code == 401


def test_admin_me_returns_owner_access_only_for_admin(client):
    main.app.dependency_overrides[get_current_user] = as_user(
        OWNER_ID, "owner@example.com", "admin"
    )

    response = client.get("/api/admin/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": OWNER_ID,
        "email": "owner@example.com",
        "role": "admin",
        "access": "owner",
    }
