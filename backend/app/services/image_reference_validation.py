"""Strict, provider-neutral validation for future image-reference uploads.

This module does not upload files, access Storage, or call an AI provider.
Ownership checks must happen before these validators are called.
"""
from dataclasses import dataclass
from pathlib import PurePath
import re

MAX_REFERENCE_BYTES = 8 * 1024 * 1024
MAX_REFERENCES_PER_SCENE = 6
MAX_BATCH_BYTES = 24 * 1024 * 1024

_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)


@dataclass(frozen=True)
class ValidatedReference:
    content: bytes
    mime_type: str
    safe_filename: str
    size_bytes: int


def _sniff_mime(data: bytes) -> str | None:
    for signature, mime, _extension in _SIGNATURES:
        if data.startswith(signature):
            return mime
    # WebP is a RIFF container with WEBP form type at bytes 8..12.
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _safe_filename(filename: str, mime_type: str) -> str:
    name = PurePath(str(filename or "reference")).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-_")[:80] or "reference"
    extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime_type]
    if not stem.lower().endswith(extension):
        stem = PurePath(stem).stem[:70] + extension
    return stem


def validate_reference_image(
    content: bytes,
    filename: str,
    declared_mime_type: str | None = None,
) -> ValidatedReference:
    if not isinstance(content, bytes) or not content:
        raise ValueError("Reference image is empty.")
    if len(content) > MAX_REFERENCE_BYTES:
        raise ValueError("Each reference image must be 8 MiB or smaller.")
    actual_mime = _sniff_mime(content)
    if actual_mime is None:
        raise ValueError("Only PNG, JPEG, and WebP reference images are accepted.")
    # Declared MIME is advisory, but reject contradictory non-empty declarations.
    if declared_mime_type and declared_mime_type.lower().split(";")[0].strip() != actual_mime:
        raise ValueError("The declared file type does not match the image content.")
    return ValidatedReference(
        content=content,
        mime_type=actual_mime,
        safe_filename=_safe_filename(filename, actual_mime),
        size_bytes=len(content),
    )


def validate_reference_batch(items: list[ValidatedReference]) -> list[ValidatedReference]:
    if not isinstance(items, list) or not items:
        raise ValueError("Select at least one reference image.")
    if len(items) > MAX_REFERENCES_PER_SCENE:
        raise ValueError("No more than 6 reference images may be used for one scene.")
    if any(not isinstance(item, ValidatedReference) for item in items):
        raise ValueError("Every batch item must be a validated reference image.")
    if any(item.size_bytes != len(item.content) for item in items):
        raise ValueError("Reference image size metadata is inconsistent.")
    if sum(item.size_bytes for item in items) > MAX_BATCH_BYTES:
        raise ValueError("The combined reference images exceed 24 MiB.")
    return items
