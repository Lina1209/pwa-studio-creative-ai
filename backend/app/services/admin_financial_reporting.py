"""Read-only, bounded administrator reporting for provider cost evidence.

This module deliberately returns aggregates only: no prompts, raw metadata,
provider usage identifiers, emails, or customer credit balances.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


MAX_REPORT_DAYS = 31
PAGE_SIZE = 100
MAX_EVENTS = 5000


class ProviderCostReportError(RuntimeError):
    pass


class ProviderCostReportNotConfiguredError(ProviderCostReportError):
    pass


def _decimal(value: Any, *, nullable: bool = False) -> Decimal | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid_decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid_decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("invalid_decimal")
    return result


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("naive_timestamp")
    return parsed.astimezone(timezone.utc)


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0000000001")), "f")


def _row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid_row")
    provider, model, source = raw.get("provider"), raw.get("model"), raw.get("cost_source")
    if not isinstance(provider, str) or not 1 <= len(provider) <= 100:
        raise ValueError("invalid_provider")
    if not isinstance(model, str) or not 1 <= len(model) <= 200:
        raise ValueError("invalid_model")
    if source not in {"reported", "estimated", "unknown"}:
        raise ValueError("invalid_cost_source")
    job_id = raw.get("job_id")
    if not isinstance(job_id, str) or len(job_id) > 64:
        raise ValueError("invalid_job_id")
    try:
        UUID(job_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid_job_id") from exc
    cost = _decimal(raw.get("cost_usd"), nullable=(source == "unknown"))
    if (source == "unknown") != (cost is None):
        raise ValueError("cost_source_mismatch")
    budget = raw.get("budget_exceeded")
    if budget is not True and budget is not False and budget is not None:
        raise ValueError("invalid_budget_state")
    created = _timestamp(raw.get("created_at"))
    return {
        "provider": provider, "model": model, "job_id": job_id,
        "source": source, "cost": cost, "budget": budget,
        "day": created.date().isoformat(),
    }


def _aggregate(rows: list[dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    total_known = Decimal("0")
    sources = {"reported": 0, "estimated": 0, "unknown": 0}
    budget = {"exceeded": 0, "within_limit": 0, "indeterminate_or_unconfigured": 0}
    providers: dict[tuple[str, str], dict[str, Any]] = {}
    days: dict[str, dict[str, Any]] = {}
    jobs: dict[str, dict[str, Any]] = {}

    for row in rows:
        source, cost = row["source"], row["cost"]
        sources[source] += 1
        if cost is not None:
            total_known += cost
        if row["budget"] is True:
            budget["exceeded"] += 1
        elif row["budget"] is False:
            budget["within_limit"] += 1
        else:
            budget["indeterminate_or_unconfigured"] += 1

        key = (row["provider"], row["model"])
        item = providers.setdefault(key, {
            "provider": key[0], "model": key[1], "events": 0,
            "known_cost_usd": Decimal("0"),
            "reported_events": 0, "estimated_events": 0, "unknown_events": 0,
        })
        item["events"] += 1
        item[f"{source}_events"] += 1
        if cost is not None:
            item["known_cost_usd"] += cost

        day = days.setdefault(row["day"], {
            "date": row["day"], "events": 0, "known_cost_usd": Decimal("0")
        })
        day["events"] += 1
        if cost is not None:
            day["known_cost_usd"] += cost

        job = jobs.setdefault(row["job_id"], {
            "job_id": row["job_id"], "events": 0, "known_cost_usd": Decimal("0")
        })
        job["events"] += 1
        if cost is not None:
            job["known_cost_usd"] += cost

    def finalize(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["known_cost_usd"] = _money(result["known_cost_usd"])
        return result

    return {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "timezone": "UTC"},
        "event_count": len(rows),
        "known_provider_cost_usd": _money(total_known),
        "cost_evidence": sources,
        "budget_events": budget,
        "by_provider_model": [finalize(v) for _, v in sorted(providers.items())],
        "by_day": [finalize(days[k]) for k in sorted(days)],
        "by_job": [finalize(jobs[k]) for k in sorted(jobs)],
        "truncated": False,
    }


def get_provider_cost_report(
    settings: Settings, *, date_from: date, date_to: date
) -> dict[str, Any]:
    if date_from > date_to or (date_to - date_from).days + 1 > MAX_REPORT_DAYS:
        raise ValueError("date_range_invalid")
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ProviderCostReportNotConfiguredError("Provider cost reporting is not configured.")

    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
    params = {
        "select": "job_id,provider,model,cost_usd,cost_source,budget_exceeded,created_at",
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
                    f"{settings.supabase_url.rstrip('/')}/rest/v1/generation_provider_cost_events",
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
        raise ProviderCostReportError("Provider cost report could not be loaded safely.") from exc

    return _aggregate(rows, date_from, date_to)
