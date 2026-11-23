import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_generation_worker_runtime_is_disabled_by_default():
    settings = Settings()
    assert settings.generation_worker_runtime_enabled is False
    assert settings.generation_worker_idle_poll_seconds == 3.0
    assert settings.generation_worker_error_backoff_seconds == 5.0


@pytest.mark.parametrize("field,value", [
    ("generation_worker_idle_poll_seconds", 0.1),
    ("generation_worker_idle_poll_seconds", 61),
    ("generation_worker_error_backoff_seconds", 0.1),
    ("generation_worker_error_backoff_seconds", 301),
])
def test_worker_runtime_intervals_are_bounded(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize("provider", ["deepseek", "DeepSeek", " DEEPSEEK "])
def test_deepseek_cannot_be_configured_as_image_generation_provider(provider):
    with pytest.raises(ValidationError, match="image input"):
        Settings(image_generation_provider=provider, image_generation_model="deepseek-flash")


def test_deepseek_remains_valid_for_text_and_vision_input_configuration():
    settings = Settings(ai_provider="deepseek", ai_model="deepseek-flash")
    assert settings.ai_provider == "deepseek"
    assert settings.ai_model == "deepseek-flash"
    assert settings.image_generation_provider is None
