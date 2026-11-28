"""Strict, provider-neutral validation for future image-reference uploads.

This module decodes and verifies image files but does not upload files, access
Storage, or call an AI provider. Ownership checks must happen before it is called.
"""
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
import re
import warnings

from PIL import Image, UnidentifiedImageError

MAX_REFERENCE_BYTES = 8 * 1024 * 1024
MAX_REFERENCES_PER_SCENE = 6
MAX_BATCH_BYTES = 24 * 1024 * 1024
MAX_IMAGE_WIDTH = 8192
MAX_IMAGE_HEIGHT = 8192
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_FRAMES = 1

_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)
_FORMAT_TO_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


@dataclass(frozen=True)
class ValidatedReference:
    content: bytes
    mime_type: str
    safe_filename: str
    size_bytes: int
    width: int
    height: int
    frame_count: int


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


def _decode_and_verify(content: bytes, expected_mime: str) -> tuple[int, int, int]:
    """Fully decode one bounded raster and reject malformed/animated inputs."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                actual_mime = _FORMAT_TO_MIME.get(image.format or "")
                if actual_mime != expected_mime:
                    raise ValueError("The image container does not match its signature.")
                width, height = image.size
                frames = int(getattr(image, "n_frames", 1))
                if width < 1 or height < 1:
                    raise ValueError("Image dimensions are invalid.")
                if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                    raise ValueError("Image dimensions exceed the 8192-pixel limit.")
                if width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image pixel count exceeds the 16-megapixel limit.")
                if frames > MAX_IMAGE_FRAMES:
                    raise ValueError("Animated or multi-frame references are not accepted.")
                image.verify()

            # verify() checks structure but does not decode pixel data; reopen and load.
            with Image.open(BytesIO(content)) as image:
                image.load()
                return width, height, frames
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("The image is corrupt, truncated, or unsafe to decode.") from exc


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
    if declared_mime_type and declared_mime_type.lower().split(";")[0].strip() != actual_mime:
        raise ValueError("The declared file type does not match the image content.")
    width, height, frames = _decode_and_verify(content, actual_mime)
    return ValidatedReference(
        content=content,
        mime_type=actual_mime,
        safe_filename=_safe_filename(filename, actual_mime),
        size_bytes=len(content),
        width=width,
        height=height,
        frame_count=frames,
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
