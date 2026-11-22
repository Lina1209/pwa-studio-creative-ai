from types import SimpleNamespace
import threading

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services import ai_service


def settings(**overrides):
    values = {
        "ai_provider": "openai",
        "ai_model": "gpt-test",
        "openai_api_key": "test-key",
        "ai_max_concurrent_requests": 2,
        "ai_queue_wait_seconds": 0,
        "ai_request_timeout_seconds": 17,
        "ai_max_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)


def test_successful_completion_returns_usage_and_cost(monkeypatch):
    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="  Ready.  "))],
            usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            model="gpt-test-version",
            _hidden_params={"response_cost": "0.012"},
        )

    monkeypatch.setattr(ai_service, "completion", fake_completion)
    result = ai_service.ask_ai(settings(), [{"role": "user", "content": "hello"}])

    assert result.text == "Ready."
    assert result.input_tokens == 4
    assert result.output_tokens == 2
    assert result.total_tokens == 6
    assert str(result.cost_usd) == "0.012"
    assert result.actual_model == "gpt-test-version"
    assert seen["timeout"] == 17
    assert seen["max_retries"] == 0
    assert seen["max_tokens"] == 2048


def test_missing_provider_key_fails_before_network_call(monkeypatch):
    def unexpected_call(**kwargs):
        raise AssertionError("Provider must not be called without credentials")

    monkeypatch.setattr(ai_service, "completion", unexpected_call)
    with pytest.raises(ai_service.AIConfigurationError):
        ai_service.ask_ai(settings(openai_api_key=None), [{"role": "user", "content": "hello"}])


def test_capacity_limit_returns_retryable_overload(monkeypatch):
    monkeypatch.setattr(
        ai_service,
        "_semaphore_for_capacity",
        lambda capacity: threading.BoundedSemaphore(0),
    )
    with pytest.raises(ai_service.AIOverloadedError):
        ai_service.ask_ai(settings(), [{"role": "user", "content": "hello"}])


def test_empty_provider_response_is_rejected(monkeypatch):
    monkeypatch.setattr(
        ai_service,
        "completion",
        lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="  "))],
            usage=None,
            model="gpt-test",
        ),
    )
    with pytest.raises(RuntimeError, match="empty response"):
        ai_service.ask_ai(settings(), [{"role": "user", "content": "hello"}])


def test_ollama_uses_configured_base_without_api_key(monkeypatch):
    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Local response"))],
            usage=None,
            model="ollama/test",
        )

    monkeypatch.setattr(ai_service, "completion", fake_completion)
    result = ai_service.ask_ai(
        settings(ai_provider="ollama", ollama_api_base="http://localhost:11434/"),
        [{"role": "user", "content": "hello"}],
    )

    assert result.text == "Local response"
    assert seen["api_base"] == "http://localhost:11434"
    assert seen["api_key"] is None


def test_output_token_limit_is_configurable_and_bounded(monkeypatch):
    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Bounded"))],
            usage=None,
            model="gpt-test",
        )

    monkeypatch.setattr(ai_service, "completion", fake_completion)
    ai_service.ask_ai(
        settings(ai_max_output_tokens=512),
        [{"role": "user", "content": "hello"}],
    )
    assert seen["max_tokens"] == 512

    with pytest.raises(ValidationError):
        Settings(ai_max_output_tokens=8193)
