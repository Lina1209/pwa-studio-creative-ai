import logging
import threading
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from litellm import completion

from app.core.config import Settings
from app.services.ai_cost_admission import (
    AIProviderBudgetUnavailable,
    mark_ai_provider_cost_unknown,
    reserve_ai_provider_cost,
    settle_ai_provider_cost,
)


logger = logging.getLogger(__name__)
_semaphore_lock = threading.Lock()
_semaphores: dict[int, threading.BoundedSemaphore] = {}


class AIConfigurationError(RuntimeError):
    pass


class AIOverloadedError(RuntimeError):
    """Raised when the bounded in-process AI capacity is full."""


@dataclass(frozen=True)
class AIResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: Decimal | None
    cost_source: str | None
    actual_model: str


def _semaphore_for_capacity(capacity: int) -> threading.BoundedSemaphore:
    # Settings are immutable for a running process; cache one gate per configured capacity.
    with _semaphore_lock:
        if capacity not in _semaphores:
            _semaphores[capacity] = threading.BoundedSemaphore(capacity)
        return _semaphores[capacity]


def _provider_credentials(settings: Settings) -> tuple[str, str | None]:
    """Resolve only explicitly enabled providers; never perform automatic fallback."""
    provider = settings.ai_provider
    if provider == "deepseek":
        return f"deepseek/{settings.ai_model}", settings.deepseek_api_key
    if provider == "gemini":
        return f"gemini/{settings.ai_model}", settings.gemini_api_key
    # Settings validation should make this unreachable; fail closed if bypassed.
    raise AIConfigurationError("Unsupported AI provider configuration.")


def _usage_value(usage, name: str) -> int | None:
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    return value if isinstance(value, int) and value >= 0 else None


def ask_ai(
    settings: Settings, messages: list[dict[str, str]], *, user_id: UUID
) -> AIResult:
    model, api_key = _provider_credentials(settings)
    provider = settings.ai_provider.strip().lower()
    if not api_key:
        raise AIConfigurationError(
            f"AI provider '{settings.ai_provider}' is selected, but its API key is not configured."
        )

    gate = _semaphore_for_capacity(settings.ai_max_concurrent_requests)
    acquired = gate.acquire(timeout=settings.ai_queue_wait_seconds)
    if not acquired:
        raise AIOverloadedError("AI capacity is currently full.")

    reservation = None
    settled = False
    request_id = uuid4()
    try:
        # Reserve worst-case USD exposure atomically before the provider call.
        reservation = reserve_ai_provider_cost(
            settings, user_id=user_id, request_id=request_id, messages=messages
        )
        completion_options = {
            "model": model,
            "messages": messages,
            "api_key": api_key,
            "timeout": settings.ai_request_timeout_seconds,
            "max_retries": settings.ai_max_retries,
            "max_tokens": settings.ai_max_output_tokens,
        }
        try:
            response = completion(**completion_options)
        except Exception as exc:
            # A timeout may happen after the provider accepted and billed the request.
            status_code = getattr(exc, "status_code", None)
            logger.error(
                "AI provider request failed: provider=%s model=%s error_type=%s status_code=%s",
                provider,
                model,
                type(exc).__name__,
                status_code if isinstance(status_code, (int, str)) else "unavailable",
            )
            raise

        usage = getattr(response, "usage", None)
        input_tokens = _usage_value(usage, "prompt_tokens")
        output_tokens = _usage_value(usage, "completion_tokens")
        total_tokens = _usage_value(usage, "total_tokens")
        cost = settle_ai_provider_cost(
            settings, reservation,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )
        settled = True
        choices = getattr(response, "choices", None)
        message = getattr(choices[0], "message", None) if choices else None
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("The AI provider returned an empty response.")

        actual_model = getattr(response, "model", None) or model
        return AIResult(
            text=content.strip(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            cost_source="server_peak_price_estimate" if cost is not None else None,
            actual_model=str(actual_model),
            request_id=request_id,
        )
    except Exception:
        if reservation is not None and not settled:
            try:
                mark_ai_provider_cost_unknown(settings, reservation)
            except AIProviderBudgetUnavailable:
                logger.error(
                    "AI provider cost reservation remains unresolved: provider=%s model=%s",
                    provider, model,
                )
        raise
    finally:
        gate.release()
