"""Strict, in-memory validation and privacy normalization for future DeepSeek Vision input.

This module deliberately does not upload, persist, or transmit images. A caller must
still enforce authenticated admission, multimodal cost reservation, and user consent.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError


ALLOWED_INPUT_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}
_DATA_URL_RE = re.compile(r"^data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)$")


class VisionInputError(ValueError):
    """Raised when an image is unsafe, malformed, or outside configured limits."""


@dataclass(frozen=True)
class ValidatedVisionImage:
    mime_type: str
    data_url: str
    byte_length: int
    width: int
    height: int
    sha256_hex: str


def validate_vision_data_url(
    value: str,
    *,
    max_bytes: int = 5 * 1024 * 1024,
    max_pixels: int = 20_000_000,
    max_dimension: int = 8192,
) -> ValidatedVisionImage:
    """Validate a bounded base64 data URL and return a metadata-stripped image.

    Only JPEG, PNG, WebP, and single-frame GIF inputs are accepted. SVG, remote
    URLs, arbitrary data URLs, animation, and oversized/decompression-bomb images
    are rejected. Re-encoding strips EXIF/GPS and ancillary metadata before any
    future provider transmission.
    """
    if not isinstance(value, str) or not value:
        raise VisionInputError("An image data URL is required.")
    if max_bytes < 1 or max_pixels < 1 or max_dimension < 1:
        raise ValueError("Image validation limits must be positive.")
    # Bound work before allocating the decoded byte buffer.
    max_encoded_chars = 4 * ((max_bytes + 2) // 3)
    if len(value) > max_encoded_chars + 64:
        raise VisionInputError("The image exceeds the allowed upload size.")

    match = _DATA_URL_RE.fullmatch(value)
    if match is None:
        raise VisionInputError("Only base64-encoded image data URLs are accepted.")
    declared_mime, encoded = match.groups()
    if declared_mime not in ALLOWED_INPUT_FORMATS:
        raise VisionInputError("This image format is not supported.")

    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise VisionInputError("The image data is not valid base64.") from exc
    if not raw or len(raw) > max_bytes:
        raise VisionInputError("The image exceeds the allowed upload size.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                actual_format = probe.format
                width, height = probe.size
                frames = getattr(probe, "n_frames", 1)
                probe.verify()
            if actual_format != ALLOWED_INPUT_FORMATS[declared_mime]:
                raise VisionInputError("The declared image format does not match its contents.")
            if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
                raise VisionInputError("The image dimensions are invalid.")
            if width > max_dimension or height > max_dimension or width * height > max_pixels:
                raise VisionInputError("The image dimensions exceed the allowed limit.")
            if frames != 1:
                raise VisionInputError("Animated images are not supported; upload a still image.")

            with Image.open(io.BytesIO(raw)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                # convert() creates a fresh pixel image and intentionally drops
                # EXIF, GPS, comments, and other source metadata.
                if declared_mime == "image/jpeg":
                    normalized = oriented.convert("RGB")
                    output_format, output_mime = "JPEG", "image/jpeg"
                    save_options = {"quality": 88, "optimize": True, "progressive": False}
                elif declared_mime == "image/webp":
                    normalized = oriented.convert("RGBA" if "A" in oriented.getbands() else "RGB")
                    output_format, output_mime = "WEBP", "image/webp"
                    save_options = {"quality": 88, "method": 4}
                else:
                    normalized = oriented.convert("RGBA" if "A" in oriented.getbands() else "RGB")
                    output_format, output_mime = "PNG", "image/png"
                    save_options = {"optimize": True}
                output = io.BytesIO()
                normalized.save(output, format=output_format, **save_options)
                clean_bytes = output.getvalue()
    except VisionInputError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise VisionInputError("The image is invalid or cannot be decoded safely.") from exc

    if not clean_bytes or len(clean_bytes) > max_bytes:
        raise VisionInputError("The normalized image exceeds the allowed upload size.")
    encoded_clean = base64.b64encode(clean_bytes).decode("ascii")
    return ValidatedVisionImage(
        mime_type=output_mime,
        data_url=f"data:{output_mime};base64,{encoded_clean}",
        byte_length=len(clean_bytes),
        width=width,
        height=height,
        sha256_hex=hashlib.sha256(clean_bytes).hexdigest(),
    )
