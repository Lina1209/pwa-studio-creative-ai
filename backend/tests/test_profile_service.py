import pytest
from fastapi import HTTPException

from app.services import profile_service


USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"


def _row(user_id=USER_B):
    return {
        "user_id": user_id,
        "username": "creator.two",
        "display_name": "Creator Two",
        "bio": "Public bio",
        "avatar_path": "avatars/public.png",
        "visibility": "public",
        "show_in_directory": True,
        "email": "private@example.com",
        "private_metadata": {"secret": True},
        "updated_at": "2026-11-24T10:00:00+00:00",
    }


def test_public_profile_serialization_is_allowlisted():
    result = profile_service._public(_row())

    assert result == {
        "user_id": USER_B,
        "username": "creator.two",
        "display_name": "Creator Two",
        "bio": "Public bio",
        "avatar_path": "avatars/public.png",
        "updated_at": "2026-11-24T10:00:00+00:00",
    }
    assert "email" not in result
    assert "private_metadata" not in result
    assert "visibility" not in result
    assert "show_in_directory" not in result


def test_public_profile_query_requires_both_public_flags_and_excludes_viewer(monkeypatch):
    calls = []

    def request(settings, method, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, params, payload))
        return [_row()]

    monkeypatch.setattr(profile_service, "_request", request)
    result = profile_service.search_public_profiles(object(), "creator", USER_A)

    assert result[0]["user_id"] == USER_B
    params = calls[0][1]
    assert params["visibility"] == "eq.public"
    assert params["show_in_directory"] == "eq.true"
    assert params["user_id"] == f"neq.{USER_A}"
    assert params["limit"] == "30"
    assert "email" not in params["select"]
    assert "private_metadata" not in params["select"]


def test_private_or_hidden_profile_returns_same_not_found_response(monkeypatch):
    monkeypatch.setattr(profile_service, "_request", lambda *args, **kwargs: [])

    with pytest.raises(HTTPException) as exc:
        profile_service.get_public_profile(object(), USER_B, USER_A)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Profile not found or not publicly available."


@pytest.mark.parametrize("query", ["x", "a" * 41, "name<script>", "%"])
def test_profile_search_rejects_short_long_or_unsupported_query(query, monkeypatch):
    called = False

    def should_not_query(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(profile_service, "_request", should_not_query)

    with pytest.raises(HTTPException) as exc:
        profile_service.search_public_profiles(object(), query, USER_A)

    assert exc.value.status_code == 422
    assert called is False


def test_invalid_account_id_is_rejected_before_storage_access(monkeypatch):
    called = False

    def should_not_query(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(profile_service, "_request", should_not_query)

    with pytest.raises(HTTPException) as exc:
        profile_service.get_public_profile("not-a-uuid", USER_A, USER_A)

    assert exc.value.status_code == 422
    assert called is False


def test_invalid_profile_update_is_rejected_before_patch(monkeypatch):
    calls = []

    def request(settings, method, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, params, payload))
        if method == "GET":
            return [_row(user_id=USER_A)]
        return []

    monkeypatch.setattr(profile_service, "_request", request)

    with pytest.raises(HTTPException) as exc:
        profile_service.update_own_profile(object(), USER_A, {"username": "bad name!"})

    assert exc.value.status_code == 422
    assert [call[0] for call in calls] == ["GET"]


def test_profile_update_is_scoped_to_verified_owner(monkeypatch):
    calls = []

    def request(settings, method, *, params=None, payload=None, prefer="return=representation"):
        calls.append((method, params, payload))
        if method == "GET":
            return [_row(user_id=USER_A)]
        return [{"user_id": USER_A, "display_name": "Updated"}]

    monkeypatch.setattr(profile_service, "_request", request)
    result = profile_service.update_own_profile(object(), USER_A, {"display_name": "Updated"})

    assert result["user_id"] == USER_A
    patch = next(call for call in calls if call[0] == "PATCH")
    assert patch[1]["user_id"] == f"eq.{USER_A}"
    assert patch[2]["display_name"] == "Updated"
    assert patch[2]["user_id"] == USER_A
