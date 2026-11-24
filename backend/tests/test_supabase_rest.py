from app.core.config import Settings
from app.services.supabase_rest import supabase_headers


def test_new_supabase_secret_key_is_not_sent_as_bearer_token():
    key = "sb_secret_example_not_a_real_secret"
    headers = supabase_headers(Settings(supabase_service_role_key=key))

    assert headers["apikey"] == key
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"
    assert headers["Prefer"] == "return=representation"


def test_legacy_service_role_jwt_is_sent_as_bearer_token():
    key = "eyJexample.legacy.jwt"
    headers = supabase_headers(Settings(supabase_service_role_key=key))

    assert headers["apikey"] == key
    assert headers["Authorization"] == f"Bearer {key}"


def test_custom_prefer_header_is_preserved():
    headers = supabase_headers(
        Settings(supabase_service_role_key="sb_secret_example"),
        prefer="return=minimal",
    )

    assert headers["Prefer"] == "return=minimal"


def test_missing_key_returns_empty_headers():
    headers = supabase_headers(Settings(supabase_service_role_key=None))

    assert headers == {}
