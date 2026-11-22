"""Service-role client for audited administrator controls over AI USD budgets."""
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class AIBudgetControlError(RuntimeError):
    pass


class AIBudgetControlNotConfigured(AIBudgetControlError):
    pass


def _amount(value: Any, *, maximum: Decimal = Decimal("1000000000")) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid_budget_amount") from exc
    if not amount.is_finite() or amount <= 0 or amount > maximum:
        raise ValueError("invalid_budget_amount")
    return amount


def _rpc(settings: Settings, name: str, payload: dict[str, Any]) -> Any:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise AIBudgetControlNotConfigured("AI budget controls are not configured.")
    key = settings.supabase_service_role_key
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
                json=payload, headers=headers,
            )
            response.raise_for_status()
            result = response.json()
    except Exception as exc:
        raise AIBudgetControlError("AI budget control operation failed safely.") from exc
    if not isinstance(result, (dict, bool)):
        raise AIBudgetControlError("AI budget control returned an invalid response.")
    return result


def update_global_budget(settings: Settings, *, enabled: bool, daily_budget_usd: Any, max_outstanding_usd: Any) -> dict:
    daily = _amount(daily_budget_usd)
    outstanding = _amount(max_outstanding_usd, maximum=daily)
    if outstanding > daily:
        raise ValueError("outstanding_exceeds_daily_budget")
    result = _rpc(settings, "update_ai_provider_global_budget", {
        "p_enabled": enabled, "p_global_daily_budget_usd": str(daily),
        "p_max_outstanding_reserved_usd": str(outstanding),
    })
    if not isinstance(result, dict):
        raise AIBudgetControlError("Global AI budget update returned an invalid response.")
    return result


def update_provider_budget(settings: Settings, *, provider: str, enabled: bool, daily_budget_usd: Any) -> dict:
    if provider not in {"deepseek", "gemini"}:
        raise ValueError("unsupported_ai_provider")
    daily = _amount(daily_budget_usd)
    result = _rpc(settings, "update_ai_provider_daily_budget", {
        "p_provider": provider, "p_enabled": enabled, "p_daily_budget_usd": str(daily),
    })
    if not isinstance(result, dict):
        raise AIBudgetControlError("Provider AI budget update returned an invalid response.")
    return result


def resolve_unknown_reservation(settings: Settings, *, request_id: UUID, resolution: str,
                                actual_estimated_cost_usd: Any | None, note: str) -> bool:
    if resolution not in {"confirm_no_charge", "record_estimated_cost"}:
        raise ValueError("unsupported_reservation_resolution")
    if not isinstance(note, str) or not 8 <= len(note.strip()) <= 1000:
        raise ValueError("resolution_note_required")
    amount = None
    if resolution == "record_estimated_cost":
        try:
            amount = Decimal(str(actual_estimated_cost_usd))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("invalid_resolution_amount") from exc
        if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000"):
            raise ValueError("invalid_resolution_amount")
    elif actual_estimated_cost_usd is not None:
        raise ValueError("unexpected_resolution_amount")
    result = _rpc(settings, "resolve_ai_provider_cost_reservation", {
        "p_request_id": str(request_id), "p_resolution": resolution,
        "p_actual_estimated_cost_usd": str(amount) if amount is not None else None,
        "p_note": note.strip(),
    })
    if not isinstance(result, bool):
        raise AIBudgetControlError("Reservation reconciliation returned an invalid response.")
    return result
