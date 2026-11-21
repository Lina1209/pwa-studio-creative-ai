import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from litellm import completion

from app.core.config import Settings


logger = logging.getLogger(__name__)


class AIConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: Decimal | None
    cost_source: str | None
    actual_model: str


def _provider_credentials(settings: Settings) -> tuple[str, str | None]:
    provider = settings.ai_provider.strip().lower()
    if provider == "openai":
        return settings.ai_model, settings.openai_api_key
    if provider == "deepseek":
        return settings.ai_model if settings.ai_model.startswith("deepseek/") else f"deepseek/{settings.ai_model}", settings.deepseek_api_key
    if provider in {"anthropic", "claude"}:
        model = settings.ai_model if settings.ai_model.startswith("anthropic/") else f"anthropic/{settings.ai_model}"
        return model, settings.anthropic_api_key
    if provider == "ollama":
        model = settings.ai_model if settings.ai_model.startswith("ollama/") else f"ollama/{settings.ai_model}"
        return model, None
    raise AIConfigurationError(f"Unsupported AI_PROVIDER: {provider}")


def _usage_value(usage, name: str) -> int | None:
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    return value if isinstance(value, int) and value >= 0 else None


def _response_cost(response) -> Decimal | None:
    hidden = getattr(response, "_hidden_params", None) or {}
    value = hidden.get("response_cost") if isinstance(hidden, dict) else None
    if value is None:
        return None
    try:
        cost = Decimal(str(value))
        return cost if cost.is_finite() and cost >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def ask_ai(settings: Settings, messages: list[dict[str, str]]) -> AIResult:
    model, api_key = _provider_credentials(settings)
    if settings.ai_provider.lower() != "ollama" and not api_key:
        raise AIConfigurationError(
            f"AI provider '{settings.ai_provider}' is selected, but its API key is not configured."
        )

    completion_options = {
        "model": model,
        "messages": messages,
        "api_key": api_key,
        "timeout": 90,
        "max_retries": 1,
    }
    if settings.ai_provider.lower() == "ollama":
        completion_options["api_base"] = settings.ollama_api_base.rstrip("/")

    try:
        response = completion(**completion_options)
    except Exception as exc:
        # Log diagnostic metadata only; never log prompts, credentials, or raw provider errors.
        status_code = getattr(exc, "status_code", None)
        logger.error(
            "AI provider request failed: provider=%s model=%s error_type=%s status_code=%s",
            settings.ai_provider,
            model,
            type(exc).__name__,
            status_code if isinstance(status_code, (int, str)) else "unavailable",
        )
        raise
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The AI provider returned an empty response.")

    usage = getattr(response, "usage", None)
    input_tokens = _usage_value(usage, "prompt_tokens")
    output_tokens = _usage_value(usage, "completion_tokens")
    total_tokens = _usage_value(usage, "total_tokens")
    actual_model = getattr(response, "model", None) or model
    cost = _response_cost(response)
    return AIResult(
        text=content.strip(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost,
        cost_source="litellm_response_cost" if cost is not None else None,
        actual_model=str(actual_model),
    )
