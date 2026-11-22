from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import Settings
from app.services import auth


USER_ID = "11111111-1111-4111-8111-111111111111"
TOKEN = "signed.jwt.token"


def configure_verified_token(monkeypatch, claims):
    settings = Settings(
        supabase_url="https://project.example.supabase.co",
        owner_user_ids=USER_ID,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda _url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="verified-public-key")
        ),
    )
    captured = {}

    def decode(token, key, **kwargs):
        captured.update({"token": token, "key": key, **kwargs})
        return claims

    monkeypatch.setattr(auth.jwt, "decode", decode)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=TOKEN)
    return credentials, captured


def test_valid_supabase_user_token_is_admin_only_when_subject_uuid_is_allowlisted(monkeypatch):
    credentials, captured = configure_verified_token(monkeypatch, {
        "sub": USER_ID,
        "iss": "https://project.example.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": 2_000_000_000,
        "role": "authenticated",
        "email": "OWNER@example.test",
    })

    user = auth.get_current_user(credentials)

    assert user.user_id == USER_ID
    assert user.email == "owner@example.test"
    assert user.role == "admin"
    assert captured["algorithms"] == ["ES256", "RS256"]
    assert captured["audience"] == "authenticated"
    assert captured["issuer"] == "https://project.example.supabase.co/auth/v1"
    assert set(captured["options"]["require"]) == {"exp", "sub", "iss", "aud"}


@pytest.mark.parametrize("role", ["service_role", "anon", "supabase_admin", None])
def test_non_user_jwt_roles_are_rejected(monkeypatch, role):
    credentials, _ = configure_verified_token(monkeypatch, {
        "sub": USER_ID,
        "role": role,
        "email": "owner@example.test",
    })

    with pytest.raises(HTTPException) as error:
        auth.get_current_user(credentials)

    assert error.value.status_code == 401


def test_non_uuid_subject_is_rejected(monkeypatch):
    credentials, _ = configure_verified_token(monkeypatch, {
        "sub": "service_role",
        "role": "authenticated",
        "email": "owner@example.test",
    })

    with pytest.raises(HTTPException) as error:
        auth.get_current_user(credentials)

    assert error.value.status_code == 401
    assert "invalid user identity" in error.value.detail


def test_invalid_signature_or_claims_return_401(monkeypatch):
    credentials, _ = configure_verified_token(monkeypatch, {})
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *args, **kwargs: (_ for _ in ()).throw(jwt.InvalidTokenError("invalid")),
    )

    with pytest.raises(HTTPException) as error:
        auth.get_current_user(credentials)

    assert error.value.status_code == 401


def test_missing_bearer_token_is_rejected(monkeypatch):
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: Settings(supabase_url="https://project.example.supabase.co"),
    )

    with pytest.raises(HTTPException) as error:
        auth.get_current_user(None)

    assert error.value.status_code == 401


def test_authentication_fails_closed_when_supabase_is_not_configured(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(supabase_url=None))

    with pytest.raises(HTTPException) as error:
        auth.get_current_user(None)

    assert error.value.status_code == 503


def test_matching_email_cannot_grant_admin_to_different_user_uuid(monkeypatch):
    credentials, _ = configure_verified_token(monkeypatch, {
        "sub": "22222222-2222-4222-8222-222222222222",
        "role": "authenticated",
        "email": "owner@example.test",
    })

    user = auth.get_current_user(credentials)

    assert user.email == "owner@example.test"
    assert user.role == "creator"


def test_malformed_owner_uuid_configuration_fails_closed(monkeypatch):
    credentials, _ = configure_verified_token(monkeypatch, {
        "sub": USER_ID,
        "role": "authenticated",
        "email": "owner@example.test",
    })
    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: Settings(
            supabase_url="https://project.example.supabase.co",
            owner_user_ids="not-a-uuid,also-not-a-uuid",
        ),
    )

    user = auth.get_current_user(credentials)

    assert user.role == "creator"


def test_oversized_bearer_token_is_rejected_before_jwks_lookup(monkeypatch):
    settings = Settings(supabase_url="https://project.example.supabase.co")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda _url: (_ for _ in ()).throw(AssertionError("JWKS must not be contacted")),
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x" * 8193)

    with pytest.raises(HTTPException) as error:
        auth.get_current_user(credentials)

    assert error.value.status_code == 401
