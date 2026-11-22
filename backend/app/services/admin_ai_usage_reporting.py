"""Owner-only aggregate AI request and token telemetry.

The cost reported by LiteLLM is an estimate, not a provider invoice.
Actual billed charges are deliberately reported as unavailable unless reconciled
against the provider's billing export.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import Settings

MAX_REPORT_DAYS = 31
PAGE_SIZE = 100
MAX_EVENTS = 5000


class AIUsageReportError(RuntimeError):
    pass


class AIUsageReportNotConfiguredError(AIUsageReportError):
    pass


def _count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid_token_count")
    return value


def _cost(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid_cost") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid_cost")
    return amount


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0000000001")), "f")


def _row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid_row")
    provider, model, endpoint = raw.get("provider"), raw.get("model"), raw.get("endpoint")
    if not isinstance(provider, str) or not 1 <= len(provider) <= 100:
        raise ValueError("invalid_provider")
    if not isinstance(model, str) or not 1 <= len(model) <= 200:
        raise ValueError("invalid_model")
    if not isinstance(endpoint, str) or not 1 <= len(endpoint) <= 80:
        raise ValueError("invalid_endpoint")
    created = raw.get("created_at")
    if not isinstance(created, str):
        raise ValueError("invalid_timestamp")
    timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("naive_timestamp")
    return {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "input_tokens": _count(raw.get("input_tokens")),
        "output_tokens": _count(raw.get("output_tokens")),
        "total_tokens": _count(raw.get("total_tokens")),
        "reported_estimated_cost_usd": _cost(raw.get("cost_usd")),
        "cost_source": raw.get("cost_source") if isinstance(raw.get("cost_source"), str) else None,
        "day": timestamp.astimezone(timezone.utc).date().isoformat(),
    }


def _aggregate(rows: list[dict[str, Any]], date_from: date, date_to: date) -> dict[str, Any]:
    totals = {
        "requests": len(rows),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "token_count_unknown_events": 0,
        "reported_estimated_cost_usd": Decimal("0"),
        "cost_unknown_events": 0,
    }
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    endpoints: dict[str, int] = {}
    days: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault((row["provider"], row["model"]), {
            "provider": row["provider"], "model": row["model"], "requests": 0,
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "token_count_unknown_events": 0,
            "reported_estimated_cost_usd": Decimal("0"), "cost_unknown_events": 0,
        })
        item["requests"] += 1
        endpoints[row["endpoint"]] = endpoints.get(row["endpoint"], 0) + 1
        day = days.setdefault(row["day"], {
            "date": row["day"], "requests": 0, "input_tokens": 0,
            "output_tokens": 0, "total_tokens": 0,
        })
        day["requests"] += 1
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            value = row[field]
            if value is None:
                totals["token_count_unknown_events"] += 1
                item["token_count_unknown_events"] += 1
            else:
                totals[field] += value
                item[field] += value
                day[field] += value
        cost = row["reported_estimated_cost_usd"]
        if cost is None:
            totals["cost_unknown_events"] += 1
            item["cost_unknown_events"] += 1
        else:
            totals["reported_estimated_cost_usd"] += cost
            item["reported_estimated_cost_usd"] += cost

    def finalize(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["reported_estimated_cost_usd"] = _money(result["reported_estimated_cost_usd"])
        return result

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat(), "timezone": "UTC"},
        "totals": {
            **totals,
            "reported_estimated_cost_usd": _money(totals["reported_estimated_cost_usd"]),
        },
        "by_provider_model": [finalize(grouped[key]) for key in sorted(grouped)],
        "by_endpoint": [{"endpoint": key, "requests": endpoints[key]} for key in sorted(endpoints)],
        "by_day": [days[key] for key in sorted(days)],
        "actual_billed_cost_usd": None,
        "billing_reconciliation": "not_available",
        "cost_disclaimer": "LiteLLM cost is an estimate. Actual provider charges and Free Tier eligibility are not available from request telemetry and must be reconciled in the provider billing console.",
        "truncated": False,
    }


def get_admin_ai_usage_report(
    settings: Settings, *, date_from: date, date_to: date
) -> dict[str, Any]:
    if date_from > date_to or (date_to - date_from).days + 1 > MAX_REPORT_DAYS:
        raise ValueError("date_range_invalid")
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise AIUsageReportNotConfiguredError("AI usage reporting is not configured.")
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
    params = {
        "select": "provider,model,endpoint,input_tokens,output_tokens,total_tokens,cost_usd,cost_source,created_at",
        "created_at": f"gte.{start.isoformat()}",
        "and": f"(created_at.lt.{end.isoformat()})",
        "order": "created_at.asc,id.asc",
        "limit": str(PAGE_SIZE),
    }
    headers = {"apikey": settings.supabase_service_role_key, "Accept": "application/json"}
    if settings.supabase_service_role_key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {settings.supabase_service_role_key}"
    rows: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=10.0) as client:
            offset = 0
            while True:
                response = client.get(
                    f"{settings.supabase_url.rstrip('/')}/rest/v1/ai_usage",
                    params=params,
                    headers={**headers, "Range": f"{offset}-{offset + PAGE_SIZE - 1}"},
                )
                response.raise_for_status()
                page = response.json()
                if not isinstance(page, list) or len(page) > PAGE_SIZE:
                    raise ValueError("invalid_page")
                rows.extend(_row(item) for item in page)
                if len(rows) > MAX_EVENTS:
                    raise OverflowError("report_event_limit")
                if len(page) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE
    except (httpx.HTTPError, ValueError, TypeError, OverflowError) as exc:
        raise AIUsageReportError("AI usage report could not be loaded safely.") from exc
    return _aggregate(rows, date_from, date_to)
