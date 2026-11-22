"""Provider-neutral contract for asynchronous image generation.

No real provider is registered here yet. Provider credentials and network clients
belong in server-side adapters, never in frontend code or request payloads.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


class ImageGenerationError(RuntimeError):
    """Safe, provider-independent failure information for job orchestration."""

    def __init__(
        self, error_code: str, *, retryable: bool = False, ambiguous: bool = False
    ):
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable
        # True only when the request may have reached the provider but its
        # acceptance/result could not be established (e.g. response lost).
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class ImageGenerationLookup:
    """Normalized result of querying a provider by the original idempotency key.

    status is one of: not_found, pending, succeeded, failed, unknown.
    A provider adapter must document lookup consistency and retention semantics.
    """

    status: str
    result: "ImageGenerationResult | None" = None
    provider_request_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"not_found", "pending", "succeeded", "failed", "unknown"}:
            raise ValueError("Unsupported provider lookup status.")
        if self.status == "succeeded" and self.result is None:
            raise ValueError("Successful provider lookup requires a result.")
        if self.status != "succeeded" and self.result is not None:
            raise ValueError("Only successful provider lookup may include a result.")
        if self.provider_request_id is not None and (
            not isinstance(self.provider_request_id, str)
            or not 1 <= len(self.provider_request_id) <= 500
        ):
            raise ValueError("Provider request ID is invalid.")
        if self.error_code is not None and not (
            isinstance(self.error_code, str) and 1 <= len(self.error_code) <= 80
            and all(ch.islower() or ch.isdigit() or ch == "_" for ch in self.error_code)
        ):
            raise ValueError("Provider lookup error code is invalid.")


class ImageProviderNotConfiguredError(ImageGenerationError):
    def __init__(self, provider: str):
        super().__init__("image_provider_not_configured", retryable=False)
        self.provider = provider


@dataclass(frozen=True)
class ImageGenerationRequest:
    prompt: str
    width: int = 1024
    height: int = 1024
    negative_prompt: str | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("Image prompt must not be empty.")
        if len(self.prompt) > 8000:
            raise ValueError("Image prompt exceeds 8000 characters.")
        if self.negative_prompt is not None and len(self.negative_prompt) > 2000:
            raise ValueError("Negative prompt exceeds 2000 characters.")
        for name, value in (("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer.")
            if not 256 <= value <= 2048 or value % 64:
                raise ValueError(f"{name} must be between 256 and 2048 and divisible by 64.")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
            or not 0 <= self.seed <= 4_294_967_295
        ):
            raise ValueError("Seed must be an unsigned 32-bit integer.")


def _detect_image_mime(payload: bytes) -> str | None:
    """Identify supported formats from file signatures, not provider claims."""
    if payload.startswith(bytes.fromhex("89504e470d0a1a0a")):
        return "image/png"
    if payload.startswith(bytes.fromhex("ffd8ff")):
        return "image/jpeg"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass(frozen=True)
class ProviderUsage:
    """Normalized provider billing evidence; USD is never customer credits."""

    cost_usd: Decimal | None = None
    cost_source: str = "unknown"
    provider_usage_id: str | None = None
    input_units: int | None = None
    output_units: int | None = None
    total_units: int | None = None
    unit_kind: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cost_source not in {"reported", "estimated", "unknown"}:
            raise ValueError("Provider usage cost source is invalid.")
        if (self.cost_source == "unknown") != (self.cost_usd is None):
            raise ValueError("Provider usage cost and source are inconsistent.")
        if self.cost_usd is not None and (
            not isinstance(self.cost_usd, Decimal)
            or not self.cost_usd.is_finite()
            or self.cost_usd < 0
            or self.cost_usd > Decimal("1000000000")
        ):
            raise ValueError("Provider usage USD amount is invalid.")
        if self.provider_usage_id is not None and (
            not isinstance(self.provider_usage_id, str)
            or not 1 <= len(self.provider_usage_id) <= 255
        ):
            raise ValueError("Provider usage identifier is invalid.")
        for value in (self.input_units, self.output_units, self.total_units):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError("Provider usage units must be nonnegative integers.")
        if self.unit_kind not in {"token", "image", "second", "character", "request", "unknown"}:
            raise ValueError("Provider usage unit kind is invalid.")
        if not isinstance(self.metadata, dict):
            raise ValueError("Provider usage metadata must be an object.")


@dataclass(frozen=True)
class ImageGenerationResult:
    image_bytes: bytes
    mime_type: str
    provider: str
    model: str
    provider_request_id: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)

    def __post_init__(self) -> None:
        if not isinstance(self.usage, ProviderUsage):
            raise ValueError("Provider usage must use the normalized ProviderUsage contract.")
        if not isinstance(self.image_bytes, bytes) or not self.image_bytes:
            raise ValueError("Provider returned an empty or invalid image payload.")
        if len(self.image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("Provider image exceeds the 20 MiB safety limit.")
        detected_mime = _detect_image_mime(self.image_bytes)
        if self.mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Provider returned an unsupported image MIME type.")
        if detected_mime != self.mime_type:
            raise ValueError("Image bytes do not match the declared MIME type.")
        if not self.provider or len(self.provider) > 100:
            raise ValueError("Provider identifier is invalid.")
        if not self.model or len(self.model) > 200:
            raise ValueError("Model identifier is invalid.")


@runtime_checkable
class ImageGenerationProvider(Protocol):
    """Adapter contract. Implementations must use server-side credentials."""

    name: str

    supports_idempotency: bool

    supports_lookup: bool

    async def lookup_by_idempotency_key(
        self, *, idempotency_key: str
    ) -> ImageGenerationLookup:
        """Look up the existing operation; must never create a new generation."""
        ...

    async def generate(
        self, request: ImageGenerationRequest, *, idempotency_key: str
    ) -> ImageGenerationResult:
        """Generate once per stable key; provider must deduplicate retries.

        The provider's idempotency retention window must cover the complete
        application retry and reconciliation horizon.
        """
        ...


class ImageProviderRegistry:
    """Explicit allowlist of configured providers; no implicit/fake fallback."""

    def __init__(self) -> None:
        self._providers: dict[str, ImageGenerationProvider] = {}

    def register(self, provider: ImageGenerationProvider) -> None:
        name = getattr(provider, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Image provider must have a non-empty name.")
        normalized = name.strip().lower()
        if normalized in self._providers:
            raise ValueError(f"Image provider '{normalized}' is already registered.")
        self._providers[normalized] = provider

    def get(self, name: str) -> ImageGenerationProvider:
        normalized = name.strip().lower()
        provider = self._providers.get(normalized)
        if provider is None:
            raise ImageProviderNotConfiguredError(normalized or "unspecified")
        return provider

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


image_provider_registry = ImageProviderRegistry()
