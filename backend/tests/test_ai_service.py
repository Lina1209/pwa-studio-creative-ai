from types import SimpleNamespace
from decimal import Decimal
import threading
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services import ai_service
from app.services.ai_cost_admission import AIProviderCostReservation, estimate_actual_cost
from app.services.vision_input import ValidatedVisionImage


@pytest.fixture(autouse=True)
def stub_cost_admission(monkeypatch):
    def reserve(settings, *, user_id, request_id, messages):
        return AIProviderCostReservation(request_id=request_id, reserved_cost_usd=Decimal("0.1"))

    monkeypatch.setattr(ai_service, "reserve_ai_provider_cost", reserve)
    monkeypatch.setattr(
        ai_service, "reserve_ai_provider_vision_cost",
        lambda settings, *, user_id, request_id, text_messages, image_count=1:
            AIProviderCostReservation(request_id, Decimal("0.2"), "vision"),
    )
    monkeypatch.setattr(
        ai_service, "settle_ai_provider_cost",
        lambda settings, reservation, *, input_tokens, output_tokens:
            estimate_actual_cost(settings, input_tokens=input_tokens, output_tokens=output_tokens),
    )
    monkeypatch.setattr(ai_service, "mark_ai_provider_cost_unknown", lambda *args, **kwargs: None)


def run_ai(settings_value, messages):
    return ai_service.ask_ai(settings_value, messages, user_id=uuid4())


def settings(**overrides):
    values = {
        "ai_provider": "deepseek",
        "ai_model": "deepseek-flash",
        "deepseek_api_key": "test-key",
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
    result = run_ai(settings(), [{"role": "user", "content": "hello"}])

    assert result.text == "Ready."
    assert result.input_tokens == 4
    assert result.output_tokens == 2
    assert result.total_tokens == 6
    assert str(result.cost_usd) == "0.0000036000"
    assert result.actual_model == "gpt-test-version"
    assert result.request_id is not None
    assert result.cost_source == "server_peak_price_estimate"
    assert seen["timeout"] == 17
    assert seen["max_retries"] == 0
    assert seen["max_tokens"] == 2048


def test_missing_provider_key_fails_before_network_call(monkeypatch):
    def unexpected_call(**kwargs):
        raise AssertionError("Provider must not be called without credentials")

    monkeypatch.setattr(ai_service, "completion", unexpected_call)
    with pytest.raises(ai_service.AIConfigurationError):
        run_ai(settings(deepseek_api_key=None), [{"role": "user", "content": "hello"}])


def test_capacity_limit_returns_retryable_overload(monkeypatch):
    monkeypatch.setattr(
        ai_service,
        "_semaphore_for_capacity",
        lambda capacity: threading.BoundedSemaphore(0),
    )
    with pytest.raises(ai_service.AIOverloadedError):
        run_ai(settings(), [{"role": "user", "content": "hello"}])


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
        run_ai(settings(), [{"role": "user", "content": "hello"}])


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
    run_ai(
        settings(ai_max_output_tokens=512),
        [{"role": "user", "content": "hello"}],
    )
    assert seen["max_tokens"] == 512

    with pytest.raises(ValidationError):
        Settings(ai_max_output_tokens=8193)


def test_unsupported_provider_is_rejected_at_configuration_boundary():
    with pytest.raises(ValidationError):
        Settings(ai_provider="openai", ai_model="gpt-test")


def test_only_deepseek_provider_is_accepted():
    with pytest.raises(ValidationError):
        Settings(ai_provider="gemini", ai_model="gemini-3.1-flash-lite")

def test_billable_ai_retries_are_disabled_at_configuration_boundary():
    with pytest.raises(ValidationError):
        Settings(ai_max_retries=1)



def test_vision_completion_sends_only_validated_data_url_and_settles_usage(monkeypatch):
    seen = {}
    image = ValidatedVisionImage(
        mime_type="image/png",
        data_url="data:image/png;base64,aGVsbG8=",
        byte_length=5,
        width=1,
        height=1,
        sha256_hex="a" * 64,
    )

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=[
                SimpleNamespace(type="text", text="Вижу маяк у моря."),
            ]))],
            usage={"prompt_tokens": 1200, "completion_tokens": 20, "total_tokens": 1220},
            model="deepseek-flash",
        )

    monkeypatch.setattr(ai_service, "completion", fake_completion)
    result = ai_service.ask_ai_vision(
        settings(),
        system_prompt="Analyze safely.",
        user_prompt="Опиши изображение.",
        image=image,
        user_id=uuid4(),
    )
    assert result.text == "Вижу маяк у моря."
    assert result.input_tokens == 1200
    assert result.output_tokens == 20
    assert result.request_id
    assert seen["model"] == "deepseek/deepseek-flash"
    assert seen["max_retries"] == 0
    assert seen["messages"][1]["content"][0] == {
        "type": "text", "text": "Опиши изображение.",
    }
    assert seen["messages"][1]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": image.data_url},
    }


def test_vision_rejects_unsupported_model_before_reservation_or_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_service, "reserve_ai_provider_vision_cost",
                        lambda *args, **kwargs: calls.append("reserve"))
    monkeypatch.setattr(ai_service, "completion",
                        lambda **kwargs: calls.append("provider"))
    image = ValidatedVisionImage(
        "image/png", "data:image/png;base64,aGVsbG8=", 5, 1, 1, "a" * 64,
    )
    with pytest.raises(ai_service.AIConfigurationError):
        ai_service.ask_ai_vision(
            settings(ai_model="deepseek-v4-pro"),
            system_prompt="system", user_prompt="prompt", image=image, user_id=uuid4(),
        )
    assert calls == []


def test_vision_provider_failure_marks_reservation_unknown(monkeypatch):
    unknown = []
    monkeypatch.setattr(
        ai_service, "mark_ai_provider_cost_unknown",
        lambda settings, reservation: unknown.append(reservation.request_modality),
    )
    monkeypatch.setattr(
        ai_service, "completion",
        lambda **kwargs: (_ for _ in ()).throw(TimeoutError("simulated timeout")),
    )
    image = ValidatedVisionImage(
        "image/png", "data:image/png;base64,aGVsbG8=", 5, 1, 1, "a" * 64,
    )
    with pytest.raises(TimeoutError):
        ai_service.ask_ai_vision(
            settings(), system_prompt="system", user_prompt="prompt",
            image=image, user_id=uuid4(),
        )
    assert unknown == ["vision"]
