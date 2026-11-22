"""Privacy-minimizing site visit counter backed by Supabase RPCs."""
import hashlib
import re
from datetime import datetime, timezone
from uuid import UUID

import httpx

from app.core.config import Settings


class SiteAnalyticsUnavailable(RuntimeError):
    pass


_ROUTE_GROUPS = {
    "home", "create", "movie", "editor", "prompts", "library", "account",
    "voice", "scenes", "assistant", "guide", "rules", "settings", "other",
}


def visitor_token_hash(token: str) -> str:
    if not isinstance(token, str) or not 20 <= len(token) <= 128:
        raise ValueError("Invalid visitor token.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise SiteAnalyticsUnavailable("Site analytics is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _rpc(settings: Settings, name: str, payload: dict) -> dict:
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
                json=payload, headers=_headers(settings),
            )
            response.raise_for_status()
            result = response.json()
    except SiteAnalyticsUnavailable:
        raise
    except Exception as exc:
        raise SiteAnalyticsUnavailable("Site analytics is temporarily unavailable.") from exc
    if not isinstance(result, dict):
        raise SiteAnalyticsUnavailable("Site analytics returned an invalid response.")
    return result


def record_visit(settings: Settings, *, event_id: UUID, visitor_token: str, route_group: str) -> dict:
    if route_group not in _ROUTE_GROUPS:
        route_group = "other"
    return _rpc(settings, "record_site_visit", {
        "p_event_id": str(event_id),
        "p_visit_date": datetime.now(timezone.utc).date().isoformat(),
        "p_visitor_token_hash": visitor_token_hash(visitor_token),
        "p_route_group": route_group,
    })


def get_visit_stats(settings: Settings) -> dict:
    result = _rpc(settings, "get_site_visit_stats", {})
    expected = ("total_page_views", "today_page_views", "today_unique_visitors",
                "last_7_days_page_views", "last_30_days_page_views")
    for key in expected:
        value = result.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SiteAnalyticsUnavailable("Site analytics returned invalid counters.")
    return result


def get_admin_visit_stats(settings: Settings) -> dict:
    """Return owner-dashboard aggregates; never returns visitor-level data."""
    result = _rpc(settings, "get_site_visit_admin_stats", {})
    base_keys = ("total_page_views", "today_page_views", "today_unique_visitors",
                 "last_7_days_page_views", "last_30_days_page_views")
    for key in base_keys:
        value = result.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SiteAnalyticsUnavailable("Site analytics returned invalid counters.")
    daily = result.get("daily_series")
    if not isinstance(daily, list) or len(daily) != 30:
        raise SiteAnalyticsUnavailable("Site analytics returned an invalid daily series.")
    for row in daily:
        if not isinstance(row, dict) or not isinstance(row.get("date"), str):
            raise SiteAnalyticsUnavailable("Site analytics returned an invalid daily series.")
        for key in ("page_views", "unique_visitors"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SiteAnalyticsUnavailable("Site analytics returned an invalid daily series.")
    routes = result.get("top_routes")
    if not isinstance(routes, list) or len(routes) > 8:
        raise SiteAnalyticsUnavailable("Site analytics returned invalid route aggregates.")
    for row in routes:
        if not isinstance(row, dict) or row.get("route_group") not in _ROUTE_GROUPS:
            raise SiteAnalyticsUnavailable("Site analytics returned invalid route aggregates.")
        value = row.get("page_views")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SiteAnalyticsUnavailable("Site analytics returned invalid route aggregates.")
    return result
