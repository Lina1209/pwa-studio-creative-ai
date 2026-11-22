import pytest

from app.services.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageProviderNotConfiguredError,
    ImageProviderRegistry,
)


def test_request_defaults_and_dimensions():
    request = ImageGenerationRequest(prompt="A lighthouse at dawn")
    assert request.width == 1024
    assert request.height == 1024


@pytest.mark.parametrize("kwargs", [
    {"prompt": ""},
    {"prompt": "   "},
    {"prompt": "x", "width": 255},
    {"prompt": "x", "height": 2050},
    {"prompt": "x", "width": 1000},
    {"prompt": "x", "seed": -1},
    {"prompt": "x", "seed": True},
])
def test_invalid_request_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ImageGenerationRequest(**kwargs)


def test_result_rejects_empty_or_unsupported_payload():
    with pytest.raises(ValueError, match="empty"):
        ImageGenerationResult(b"", "image/png", "test", "model")
    with pytest.raises(ValueError, match="MIME"):
        ImageGenerationResult(bytes.fromhex("89504e470d0a1a0a"), "image/svg+xml", "test", "model")
    with pytest.raises(ValueError, match="do not match"):
        ImageGenerationResult(b"not-an-image", "image/png", "test", "model")


def test_registry_does_not_fall_back_to_a_fake_provider():
    registry = ImageProviderRegistry()
    with pytest.raises(ImageProviderNotConfiguredError):
        registry.get("openai")
    assert registry.names() == ()


def test_registry_normalizes_names_and_rejects_duplicates():
    class FakeProvider:
        name = "Test-Image"

    registry = ImageProviderRegistry()
    provider = FakeProvider()
    registry.register(provider)
    assert registry.get("test-image") is provider
    with pytest.raises(ValueError, match="already registered"):
        registry.register(provider)
