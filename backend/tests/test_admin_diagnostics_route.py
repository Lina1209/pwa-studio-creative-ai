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


def _as_user(user_id: str, role: str):
    return lambda: StudioUser(
        user_id=user_id,
        email=None,
        role=role,
    )


def test_admin_diagnostics_requires_authentication(client, monkeypatch):
    def unexpected_inspection(_settings):
        raise AssertionError("Diagnostics must not run before admin authorization.")

    monkeypatch.setattr(main, "inspect_supabase", unexpected_inspection)

    response = client.get("/api/admin/diagnostics/supabase")

    assert response.status_code == 401


def test_creator_cannot_access_admin_diagnostics(client, monkeypatch):
    main.app.dependency_overrides[get_current_user] = _as_user(CREATOR_ID, "creator")

    def unexpected_inspection(_settings):
        raise AssertionError("Diagnostics must not run for a creator.")

    monkeypatch.setattr(main, "inspect_supabase", unexpected_inspection)

    response = client.get("/api/admin/diagnostics/supabase")

    assert response.status_code == 403


def test_admin_can_access_read_only_diagnostics(client, monkeypatch):
    main.app.dependency_overrides[get_current_user] = _as_user(OWNER_ID, "admin")
    calls = []

    def fake_inspection(settings):
        calls.append(settings)
        return {
            "supabase_configured": True,
            "supabase_key_kind": "sb_secret_or_other",
            "rest_api_reachable": True,
            "tables": {"projects": "available"},
        }

    monkeypatch.setattr(main, "inspect_supabase", fake_inspection)

    response = client.get("/api/admin/diagnostics/supabase")

    assert response.status_code == 200
    assert response.json()["tables"]["projects"] == "available"
    assert len(calls) == 1
