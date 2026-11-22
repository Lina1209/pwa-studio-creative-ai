from uuid import uuid4

import pytest

from app.services.site_analytics import SiteAnalyticsUnavailable, get_visit_stats, record_visit, visitor_token_hash


def test_visitor_token_is_hashed_and_never_returned():
    token = "x" * 32
    digest = visitor_token_hash(token)
    assert len(digest) == 64
    assert digest != token


def test_invalid_visitor_token_rejected():
    with pytest.raises(ValueError):
        visitor_token_hash("short")


def test_unknown_route_is_normalized(monkeypatch):
    from app.services import site_analytics
    captured = {}
    monkeypatch.setattr(site_analytics, "_rpc", lambda settings, name, payload: captured.update(payload) or {"ok": True})
    result = record_visit(object(), event_id=uuid4(), visitor_token="v" * 32, route_group="../../admin")
    assert result == {"ok": True}
    assert captured["p_route_group"] == "other"


def test_stats_validate_nonnegative_integer_counts(monkeypatch):
    from app.services import site_analytics
    valid = {"total_page_views": 120, "today_page_views": 4, "today_unique_visitors": 3,
             "last_7_days_page_views": 20, "last_30_days_page_views": 80}
    monkeypatch.setattr(site_analytics, "_rpc", lambda *args: valid)
    assert get_visit_stats(object())["total_page_views"] == 120
    monkeypatch.setattr(site_analytics, "_rpc", lambda *args: {**valid, "total_page_views": True})
    with pytest.raises(SiteAnalyticsUnavailable):
        get_visit_stats(object())
