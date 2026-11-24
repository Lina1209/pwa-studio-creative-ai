from unittest.mock import Mock

import httpx

from app.core.config import Settings
from app.services import diagnostics_service


def _settings(key="sb_secret_test"):
    return Settings(
        app_env="test",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key=key,
    )


def test_diagnostics_report_table_availability_without_reading_rows(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        return Mock(status_code=200)

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Mock(status_code=200)

    monkeypatch.setattr(diagnostics_service.httpx, "get", fake_get)
    monkeypatch.setattr(diagnostics_service.httpx, "request", fake_request)

    result = diagnostics_service.inspect_supabase(_settings())

    assert result["supabase_configured"] is True
    assert result["supabase_key_kind"] == "sb_secret_or_other"
    assert result["rest_api_reachable"] is True
    assert set(result["tables"].values()) == {"available"}
    assert len(calls) == len(diagnostics_service.TABLE_CHECKS)
    assert all(method == "HEAD" for method, _, _ in calls)
    assert all(kwargs["params"]["limit"] == "0" for _, _, kwargs in calls)


def test_diagnostics_classify_missing_and_inaccessible_tables(monkeypatch):
    statuses = iter([200, 200, 404, 403, "network_error", 200, 200, 200])

    monkeypatch.setattr(
        diagnostics_service.httpx,
        "get",
        lambda *args, **kwargs: Mock(status_code=200),
    )

    def fake_request(*args, **kwargs):
        status = next(statuses)
        if status == "network_error":
            raise httpx.ConnectError("simulated network failure")
        return Mock(status_code=status)

    monkeypatch.setattr(diagnostics_service.httpx, "request", fake_request)

    result = diagnostics_service.inspect_supabase(_settings())

    assert result["tables"]["profiles"] == "available"
    assert result["tables"]["projects"] == "available"
    assert result["tables"]["notifications"] == "missing_or_not_exposed"
    assert result["tables"]["conversations"] == "not_accessible"
    assert result["tables"]["messages"] == "unreachable"


def test_diagnostics_do_not_make_requests_without_supabase_configuration(monkeypatch):
    def unexpected_request(*args, **kwargs):
        raise AssertionError("No network request should be made.")

    monkeypatch.setattr(diagnostics_service.httpx, "get", unexpected_request)
    monkeypatch.setattr(diagnostics_service.httpx, "request", unexpected_request)

    result = diagnostics_service.inspect_supabase(
        Settings(app_env="test", supabase_url=None, supabase_service_role_key=None)
    )

    assert result["supabase_configured"] is False
    assert result["supabase_key_kind"] == "missing"
    assert result["rest_api_reachable"] is False
    assert set(result["tables"].values()) == {"not_checked"}


def test_diagnostics_never_include_secret_key(monkeypatch):
    secret = "sb_secret_do_not_return"
    monkeypatch.setattr(
        diagnostics_service.httpx,
        "get",
        lambda *args, **kwargs: Mock(status_code=200),
    )
    monkeypatch.setattr(
        diagnostics_service.httpx,
        "request",
        lambda *args, **kwargs: Mock(status_code=200),
    )

    result = diagnostics_service.inspect_supabase(_settings(secret))

    assert secret not in repr(result)
