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
