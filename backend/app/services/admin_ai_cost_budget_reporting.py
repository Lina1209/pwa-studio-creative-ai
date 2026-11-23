"""Read-only owner report for atomic synchronous AI USD budget reservations."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import Settings


class AICostBudgetReportError(RuntimeError):
    pass


class AICostBudgetReportNotConfiguredError(AICostBudgetReportError):
    pass


def _decimal(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid_budget_amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid_budget_amount")
    return amount


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0000000001")), "f")


def _fetch_rows(client: httpx.Client, url: str, headers: dict[str, str], params: dict[str, str]) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        response = client.get(
            url, params={**params, "limit": "100"},
            headers={**headers, "Range": f"{offset}-{offset + 99}"},
        )
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list) or len(page) > 100:
            raise ValueError("invalid_budget_report_page")
        if any(not isinstance(row, dict) for row in page):
            raise ValueError("invalid_budget_report_row")
        rows.extend(page)
        if len(rows) > 10000:
            raise OverflowError("budget_report_event_limit")
        if len(page) < 100:
            return rows
        offset += 100


def get_admin_ai_cost_budget_report(settings: Settings) -> dict:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise AICostBudgetReportNotConfiguredError("AI cost budget reporting is not configured.")
    base = settings.supabase_url.rstrip("/") + "/rest/v1"
    key = settings.supabase_service_role_key
    headers = {"apikey": key, "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        with httpx.Client(timeout=10.0) as client:
            policy_rows = _fetch_rows(
                client, base + "/ai_provider_budget_policy", headers,
                {"select": "enabled,global_daily_budget_usd,max_outstanding_reserved_usd", "singleton": "eq.true"},
            )
            provider_rows = _fetch_rows(
                client, base + "/ai_provider_daily_budgets", headers,
                {"select": "provider,daily_budget_usd,enabled", "order": "provider.asc"},
            )
            active_rows = _fetch_rows(
                client, base + "/ai_provider_cost_reservations", headers,
                {"select": "request_id,provider,model,request_modality,status,reserved_cost_usd,actual_estimated_cost_usd,created_at", "status": "in.(reserved,unknown)"},
            )
            settled_rows = _fetch_rows(
                client, base + "/ai_provider_cost_reservations", headers,
                {"select": "provider,request_modality,status,reserved_cost_usd,actual_estimated_cost_usd", "status": "eq.settled", "settled_at": f"gte.{day_start}"},
            )
    except (httpx.HTTPError, ValueError, TypeError, OverflowError) as exc:
        raise AICostBudgetReportError("AI cost budget report could not be loaded safely.") from exc

    if len(policy_rows) != 1:
        raise AICostBudgetReportError("AI global budget policy is missing or ambiguous.")
    policy = policy_rows[0]
    try:
        global_budget = _decimal(policy["global_daily_budget_usd"])
        outstanding_cap = _decimal(policy["max_outstanding_reserved_usd"])
        settled_global = sum((_decimal(row["actual_estimated_cost_usd"]) for row in settled_rows), Decimal("0"))
        active_global = sum((_decimal(row["reserved_cost_usd"]) for row in active_rows), Decimal("0"))
    except (KeyError, ValueError) as exc:
        raise AICostBudgetReportError("AI cost budget data is invalid.") from exc

    providers = []
    for provider in ("deepseek", "gemini"):
        matches = [row for row in provider_rows if row.get("provider") == provider]
        if len(matches) != 1:
            raise AICostBudgetReportError("AI provider daily budget policy is missing or ambiguous.")
        try:
            limit = _decimal(matches[0]["daily_budget_usd"])
            spent = sum((
                _decimal(row["actual_estimated_cost_usd"])
                for row in settled_rows if row.get("provider") == provider
            ), Decimal("0"))
            active = [row for row in active_rows if row.get("provider") == provider]
            reserved = sum((_decimal(row["reserved_cost_usd"]) for row in active), Decimal("0"))
        except (KeyError, ValueError) as exc:
            raise AICostBudgetReportError("AI provider budget data is invalid.") from exc
        unknown_count = sum(1 for row in active if row.get("status") == "unknown")
        used = spent + reserved
        status = "disabled" if not matches[0].get("enabled") else (
            "unknown_costs" if unknown_count else
            "threshold_reached" if used >= limit else
            "warning" if used >= limit * Decimal("0.8") else "within_limit"
        )
        providers.append({
            "provider": provider,
            "enabled": bool(matches[0].get("enabled")),
            "daily_budget_usd": _money(limit),
            "settled_estimated_spend_usd": _money(spent),
            "outstanding_reserved_usd": _money(reserved),
            "committed_total_usd": _money(used),
            "remaining_usd": _money(max(Decimal("0"), limit - used)),
            "unknown_reservations": unknown_count,
            "status": status,
        })

    by_modality = []
    for modality in ("text", "vision"):
        modality_settled = sum((
            _decimal(row["actual_estimated_cost_usd"])
            for row in settled_rows if row.get("request_modality") == modality
        ), Decimal("0"))
        modality_active = [
            row for row in active_rows if row.get("request_modality") == modality
        ]
        modality_reserved = sum((
            _decimal(row["reserved_cost_usd"]) for row in modality_active
        ), Decimal("0"))
        by_modality.append({
            "request_modality": modality,
            "settled_estimated_spend_usd": _money(modality_settled),
            "outstanding_reserved_usd": _money(modality_reserved),
            "committed_total_usd": _money(modality_settled + modality_reserved),
            "active_reservations": len(modality_active),
            "unknown_reservations": sum(
                1 for row in modality_active if row.get("status") == "unknown"
            ),
        })

    global_committed = settled_global + active_global
    return {
        "date_utc": now.date().isoformat(),
        "enabled": bool(policy.get("enabled")),
        "global_daily_budget_usd": _money(global_budget),
        "global_settled_estimated_spend_usd": _money(settled_global),
        "global_outstanding_reserved_usd": _money(active_global),
        "global_committed_total_usd": _money(global_committed),
        "global_remaining_usd": _money(max(Decimal("0"), global_budget - global_committed)),
        "max_outstanding_reserved_usd": _money(outstanding_cap),
        "providers": providers,
        "by_modality": by_modality,
        "unknown_reservations": [
            {"request_id": row["request_id"], "provider": row["provider"], "model": row["model"],
             "request_modality": row.get("request_modality", "text"),
             "reserved_cost_usd": _money(_decimal(row["reserved_cost_usd"])), "created_at": row["created_at"]}
            for row in active_rows if row.get("status") == "unknown"
        ],
        "actual_billed_cost_usd": None,
        "billing_reconciliation": "not_available",
        "note": "Atomic admission uses conservative server-side peak paid-tier token estimates. Unknown outcomes keep their full reserve locked. This is not invoice-level billing reconciliation.",
    }
