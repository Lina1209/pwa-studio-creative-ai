from litellm import completion

from app.core.config import Settings


class AIConfigurationError(RuntimeError):
    pass


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


def ask_ai(settings: Settings, messages: list[dict[str, str]]) -> str:
    model, api_key = _provider_credentials(settings)
    if settings.ai_provider.lower() != "ollama" and not api_key:
        raise AIConfigurationError(
            f"AI provider '{settings.ai_provider}' is selected, but its API key is not configured."
        )

    response = completion(
        model=model,
        messages=messages,
        api_key=api_key,
        timeout=90,
        max_retries=1,
    )
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The AI provider returned an empty response.")
    return content.strip()
