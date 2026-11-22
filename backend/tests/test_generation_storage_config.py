import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_private_generation_storage_defaults_to_media_bucket():
    settings = Settings()
    assert settings.generation_storage_bucket == "studio-media"
    assert settings.generation_storage_timeout_seconds == 30.0


@pytest.mark.parametrize("value", ["", "/", "bucket/path", "x" * 101])
def test_generation_storage_bucket_name_is_validated(value):
    with pytest.raises(ValidationError):
        Settings(generation_storage_bucket=value)


@pytest.mark.parametrize("value", [0.5, 181])
def test_generation_storage_timeout_is_bounded(value):
    with pytest.raises(ValidationError):
        Settings(generation_storage_timeout_seconds=value)
