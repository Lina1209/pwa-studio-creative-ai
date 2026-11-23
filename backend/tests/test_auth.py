from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import Settings
from app.services import auth


OWNER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"


def configure_auth(monkeypatch, settings, claims):
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda _url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="test-public-key")
        ),
    )
    monkeypatch.setattr(auth.jwt, "decode", lambda *args, **kwargs: claims)


def credentials():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token")


def test_owner_is_admin_by_immutable_user_id(monkeypatch):
    settings = Settings(
        supabase_url="https://project.supabase.co",
        owner_user_id=OWNER_ID,
        owner_email="different@example.com",
    )
    configure_auth(monkeypatch, settings, {"sub": OWNER_ID, "email": "owner@example.com"})

    user = auth.get_current_user(credentials())

    assert user.user_id == OWNER_ID
    assert user.role == "admin"


def test_non_owner_cannot_become_admin_by_matching_email_when_id_is_configured(monkeypatch):
    settings = Settings(
        supabase_url="https://project.supabase.co",
        owner_user_id=OWNER_ID,
        owner_email="owner@example.com",
    )
    configure_auth(monkeypatch, settings, {"sub": OTHER_ID, "email": "owner@example.com"})

    user = auth.get_current_user(credentials())

    assert user.role == "creator"


def test_email_fallback_is_case_insensitive_when_owner_id_is_not_configured(monkeypatch):
    settings = Settings(
        supabase_url="https://project.supabase.co",
        owner_email="Owner@Example.com",
    )
    configure_auth(monkeypatch, settings, {"sub": OWNER_ID, "email": "OWNER@example.com"})

    user = auth.get_current_user(credentials())

    assert user.role == "admin"


def test_missing_bearer_token_is_rejected(monkeypatch):
    settings = Settings(supabase_url="https://project.supabase.co")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(None)

    assert exc.value.status_code == 401


def test_creator_is_rejected_by_admin_guard():
    user = auth.StudioUser(user_id=OTHER_ID, email="creator@example.com", role="creator")

    with pytest.raises(HTTPException) as exc:
        auth.require_admin(user)

    assert exc.value.status_code == 403


def test_admin_passes_admin_guard():
    user = auth.StudioUser(user_id=OWNER_ID, email="owner@example.com", role="admin")

    assert auth.require_admin(user) is user
