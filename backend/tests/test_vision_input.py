import base64
import io

import pytest
from PIL import Image

from app.services.vision_input import VisionInputError, validate_vision_data_url


def _data_url(image_format="PNG", *, size=(16, 12), frames=1):
    output = io.BytesIO()
    images = [Image.new("RGB", size, (40 + index, 80, 120)) for index in range(frames)]
    if frames > 1:
        images[0].save(output, format=image_format, save_all=True, append_images=images[1:], duration=100, loop=0)
    else:
        images[0].save(output, format=image_format)
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}[image_format]
    return f"data:{mime};base64," + base64.b64encode(output.getvalue()).decode("ascii")


@pytest.mark.parametrize("image_format,expected_mime", [
    ("JPEG", "image/jpeg"), ("PNG", "image/png"),
    ("WEBP", "image/webp"), ("GIF", "image/png"),
])
def test_valid_still_images_are_normalized(image_format, expected_mime):
    result = validate_vision_data_url(_data_url(image_format))
    assert result.mime_type == expected_mime
    assert result.width == 16
    assert result.height == 12
    assert result.byte_length > 0
    assert len(result.sha256_hex) == 64
    assert result.data_url.startswith(expected_mime + ";") is False
    assert result.data_url.startswith(f"data:{expected_mime};base64,")


def test_remote_urls_and_non_image_data_urls_are_rejected():
    for value in ("https://example.com/image.png", "data:text/html;base64,PGgxPkhlbGxvPC9oMT4="):
        with pytest.raises(VisionInputError):
            validate_vision_data_url(value)


def test_svg_and_unsupported_mime_are_rejected():
    svg = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>").decode()
    with pytest.raises(VisionInputError):
        validate_vision_data_url(f"data:image/svg+xml;base64,{svg}")


def test_invalid_base64_is_rejected():
    with pytest.raises(VisionInputError):
        validate_vision_data_url("data:image/png;base64,%%%not-base64%%%")


def test_declared_mime_must_match_actual_file_format():
    png = _data_url("PNG").split(",", 1)[1]
    with pytest.raises(VisionInputError):
        validate_vision_data_url(f"data:image/jpeg;base64,{png}")


def test_raw_and_normalized_size_limits_are_enforced():
    with pytest.raises(VisionInputError):
        validate_vision_data_url(_data_url(), max_bytes=8)


def test_pixel_limit_is_enforced_before_full_decode():
    with pytest.raises(VisionInputError):
        validate_vision_data_url(_data_url(size=(100, 100)), max_pixels=9999)


def test_dimension_limit_is_enforced():
    with pytest.raises(VisionInputError):
        validate_vision_data_url(_data_url(size=(100, 20)), max_dimension=99)


def test_animated_gif_is_rejected():
    with pytest.raises(VisionInputError):
        validate_vision_data_url(_data_url("GIF", frames=2))


def test_empty_or_non_string_input_is_rejected():
    for value in ("", None, b"image"):
        with pytest.raises(VisionInputError):
            validate_vision_data_url(value)
