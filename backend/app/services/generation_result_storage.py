"""Strict validation contract for private generation-result objects.

This module deliberately does not upload files or call Supabase Storage. A future
storage adapter must fetch authoritative object metadata and pass it here before
the worker is allowed to call complete_generation_job.
"""
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from app.services.image_generation import ALLOWED_IMAGE_MIME_TYPES, MAX_IMAGE_BYTES


class GenerationResultStorageError(RuntimeError):
    """Permanent result validation failure; contains no object contents or secrets."""

    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


class GenerationStorageAdapterError(RuntimeError):
    """Typed storage I/O failure with an explicit retry policy."""

    def __init__(self, error_code: str, *, retryable: bool = False):
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True)
class StoredObjectMetadata:
    bucket: str
    object_path: str
    is_private: bool
    content_type: str
    size_bytes: int
    sha256_hex: str


@dataclass(frozen=True)
class VerifiedGenerationAsset:
    bucket: str
    object_path: str
    content_type: str
    size_bytes: int
    sha256_hex: str


def validate_generation_result_object(
    *,
    owner_id: UUID,
    expected_bucket: str,
    expected_object_path: str,
    expected_sha256_hex: str,
    metadata: StoredObjectMetadata,
) -> VerifiedGenerationAsset:
    """Validate authoritative storage metadata before marking a job successful.

    The caller must obtain metadata from the storage service itself, not
    from a client request or provider response.
    """
    if not expected_bucket or len(expected_bucket) > 100:
        raise GenerationResultStorageError("invalid_expected_bucket")

    if not isinstance(expected_object_path, str) or not expected_object_path:
        raise GenerationResultStorageError("invalid_object_path")
    if len(expected_object_path) > 1024 or expected_object_path.startswith("/"):
        raise GenerationResultStorageError("invalid_object_path")

    parts = expected_object_path.split("/")
    if (
        len(parts) < 2
        or any(not part or part in {".", ".."} for part in parts)
        or "\\" in expected_object_path
        or parts[0] != str(owner_id)
    ):
        raise GenerationResultStorageError("object_owner_or_path_mismatch")

    if metadata.bucket != expected_bucket:
        raise GenerationResultStorageError("object_bucket_mismatch")
    if metadata.object_path != expected_object_path:
        raise GenerationResultStorageError("object_path_mismatch")
    if metadata.is_private is not True:
        raise GenerationResultStorageError("object_bucket_must_be_private")

    if metadata.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise GenerationResultStorageError("object_mime_not_allowed")
    if (
        isinstance(metadata.size_bytes, bool)
        or not isinstance(metadata.size_bytes, int)
        or not 0 < metadata.size_bytes <= MAX_IMAGE_BYTES
    ):
        raise GenerationResultStorageError("object_size_out_of_range")

    if (
        not isinstance(expected_sha256_hex, str)
        or len(expected_sha256_hex) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256_hex)
    ):
        raise GenerationResultStorageError("invalid_expected_checksum")
    if metadata.sha256_hex != expected_sha256_hex:
        raise GenerationResultStorageError("object_checksum_mismatch")

    return VerifiedGenerationAsset(
        bucket=metadata.bucket,
        object_path=metadata.object_path,
        content_type=metadata.content_type,
        size_bytes=metadata.size_bytes,
        sha256_hex=metadata.sha256_hex,
    )


def calculate_sha256(payload: bytes) -> str:
    """Return the canonical SHA-256 digest for the bytes actually uploaded."""
    if not isinstance(payload, bytes) or not payload:
        raise GenerationResultStorageError("empty_or_invalid_upload_payload")
    if len(payload) > MAX_IMAGE_BYTES:
        raise GenerationResultStorageError("upload_payload_too_large")
    return sha256(payload).hexdigest()
