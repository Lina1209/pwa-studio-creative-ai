"""Atomic USD reservations for synchronous DeepSeek requests.

The estimator intentionally uses peak paid-tier token rates, not free-tier assumptions.
The reserve is based on UTF-8 input bytes (a conservative token upper bound), maximum
output tokens, and a 25% safety margin. Provider invoices remain authoritative.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from uuid import UUID

import httpx

from app.core.config import Settings


PRICE_USD_PER_MILLION = {
    ("deepseek", "deepseek-flash"): (Decimal("0.30"), Decimal("1.20")),
    ("deepseek", "deepseek-v4-pro"): (Decimal("1.32"), Decimal("3.96")),
}
SAFETY_MULTIPLIER = Decimal("1.25")
MONEY_QUANTUM = Decimal("0.0000000001")


class AIProviderBudgetUnavailable(RuntimeError):
    pass


class AIProviderBudgetRejected(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("AI provider spending limit has been reached.")


@dataclass(frozen=True)
class AIProviderCostReservation:
    request_id: UUID
    reserved_cost_usd: Decimal


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise AIProviderBudgetUnavailable("AI provider cost controls are not configured.")
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _rpc(settings: Settings, name: str, payload: dict):
    request_headers = _headers(settings)
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{name}"
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload, headers=request_headers)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        raise AIProviderBudgetUnavailable("AI provider cost control is temporarily unavailable.") from exc


def estimate_worst_case_cost(
    settings: Settings, messages: list[dict[str, str]]
) -> tuple[int, Decimal]:
    price = PRICE_USD_PER_MILLION.get((settings.ai_provider, settings.ai_model))
    if price is None:
        raise AIProviderBudgetUnavailable("No approved server-side price exists for the selected AI model.")
    import json

    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    input_bytes = len(serialized)
    if input_bytes < 1 or input_bytes > settings.ai_max_input_bytes:
        raise AIProviderBudgetRejected("input_size_limit")
    input_rate, output_rate = price
    raw = (
        Decimal(input_bytes) * input_rate
        + Decimal(settings.ai_max_output_tokens) * output_rate
    ) / Decimal(1_000_000)
    reserved = (raw * SAFETY_MULTIPLIER).quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)
    return input_bytes, max(reserved, MONEY_QUANTUM)


def reserve_ai_provider_cost(
    settings: Settings, *, user_id: UUID, request_id: UUID, messages: list[dict[str, str]]
) -> AIProviderCostReservation:
    _, reserved = estimate_worst_case_cost(settings, messages)
    result = _rpc(settings, "reserve_ai_provider_cost", {
        "p_request_id": str(request_id),
        "p_user_id": str(user_id),
        "p_provider": settings.ai_provider,
        "p_model": settings.ai_model,
        "p_reserved_cost_usd": format(reserved, "f"),
    })
    if not isinstance(result, dict) or not isinstance(result.get("admitted"), bool):
        raise AIProviderBudgetUnavailable("AI provider cost control returned an invalid response.")
    if result["admitted"] is not True:
        reason = result.get("reason")
        if reason not in {
            "global_budget_disabled", "provider_budget_disabled",
            "global_daily_budget_reached", "provider_daily_budget_reached",
            "outstanding_exposure_limit", "duplicate_reservation",
        }:
            reason = "budget_limited"
        raise AIProviderBudgetRejected(reason)
    return AIProviderCostReservation(request_id=request_id, reserved_cost_usd=reserved)


def estimate_actual_cost(
    settings: Settings, *, input_tokens: int | None, output_tokens: int | None
) -> Decimal | None:
    if (
        isinstance(input_tokens, bool) or not isinstance(input_tokens, int) or input_tokens < 0
        or isinstance(output_tokens, bool) or not isinstance(output_tokens, int) or output_tokens < 0
    ):
        return None
    price = PRICE_USD_PER_MILLION.get((settings.ai_provider, settings.ai_model))
    if price is None:
        return None
    input_rate, output_rate = price
    amount = (
        Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate
    ) / Decimal(1_000_000)
    return amount.quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)


def settle_ai_provider_cost(
    settings: Settings,
    reservation: AIProviderCostReservation,
    *,
    input_tokens: int | None,
    output_tokens: int | None,
) -> Decimal | None:
    estimate = estimate_actual_cost(
        settings, input_tokens=input_tokens, output_tokens=output_tokens
    )
    payload = {
        "p_request_id": str(reservation.request_id),
        "p_actual_estimated_cost_usd": format(estimate, "f") if estimate is not None else None,
        "p_cost_source": "server_peak_price_estimate" if estimate is not None else None,
    }
    result = _rpc(settings, "settle_ai_provider_cost", payload)
    if result is not True:
        raise AIProviderBudgetUnavailable("AI provider cost reservation could not be settled.")
    return estimate


def mark_ai_provider_cost_unknown(
    settings: Settings, reservation: AIProviderCostReservation
) -> None:
    result = _rpc(settings, "settle_ai_provider_cost", {
        "p_request_id": str(reservation.request_id),
        "p_actual_estimated_cost_usd": None,
        "p_cost_source": None,
    })
    if result is not True:
        raise AIProviderBudgetUnavailable("AI provider cost reservation could not be marked unknown.")


def estimate_worst_case_vision_cost(
    settings: Settings,
    text_messages: list[dict[str, str]],
    *,
    image_count: int = 1,
) -> tuple[int, int, Decimal]:
    """Estimate a fail-closed Vision reservation without contacting any provider.

    The browser never supplies token counts. Text is serialized canonically and bounded
    by the existing byte limit; image tokens use DeepSeek's documented 1,024-token
    per-image upper bound. This is an estimator only: the Vision RPC/ledger path must
    be added separately before a paid Vision request can be enabled.
    """
    if settings.ai_provider != "deepseek" or settings.ai_model != "deepseek-flash":
        raise AIProviderBudgetUnavailable(
            "Vision cost admission is approved only for DeepSeek Flash."
        )
    if isinstance(image_count, bool) or not isinstance(image_count, int) or image_count != 1:
        raise AIProviderBudgetRejected("vision_image_count_limit")

    import json

    if not isinstance(text_messages, list) or not text_messages:
        raise AIProviderBudgetRejected("input_size_limit")
    for message in text_messages:
        if (
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or not isinstance(message.get("role"), str)
            or not isinstance(message.get("content"), str)
        ):
            raise AIProviderBudgetRejected("input_size_limit")

    serialized = json.dumps(
        text_messages, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    text_input_bytes = len(serialized)
    if text_input_bytes < 1 or text_input_bytes > settings.ai_max_input_bytes:
        raise AIProviderBudgetRejected("input_size_limit")

    image_tokens = 1024 * image_count
    input_rate, output_rate = PRICE_USD_PER_MILLION[("deepseek", "deepseek-flash")]
    raw = (
        Decimal(text_input_bytes + image_tokens) * input_rate
        + Decimal(settings.ai_max_output_tokens) * output_rate
    ) / Decimal(1_000_000)
    reserved = (raw * SAFETY_MULTIPLIER).quantize(
        MONEY_QUANTUM, rounding=ROUND_CEILING
    )
    return text_input_bytes, image_tokens, max(reserved, MONEY_QUANTUM)
