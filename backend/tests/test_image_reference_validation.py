import unittest
from dataclasses import replace
from io import BytesIO

from PIL import Image

from app.services.image_reference_validation import (
    MAX_REFERENCE_BYTES,
    MAX_IMAGE_WIDTH,
    MAX_IMAGE_PIXELS,
    validate_reference_batch,
    validate_reference_image,
)


def make_image(fmt="PNG", size=(16, 12), frames=1):
    output = BytesIO()
    # Keep frames visibly distinct after lossy WebP encoding; otherwise the
    # encoder may optimize near-identical frames into a single still image.
    images = [Image.new("RGB", size, (20 + 100 * index, 40, 60)) for index in range(frames)]
    if frames > 1:
        images[0].save(output, format=fmt, save_all=True, append_images=images[1:], duration=100, loop=0)
    else:
        images[0].save(output, format=fmt)
    return output.getvalue()


class ImageReferenceValidationTests(unittest.TestCase):
    def test_accepts_fully_decoded_png_and_sanitizes_filename(self):
        result = validate_reference_image(make_image(), "../../portrait.png", "image/png")
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual(result.safe_filename, "portrait.png")
        self.assertEqual((result.width, result.height, result.frame_count), (16, 12, 1))

    def test_accepts_jpeg_and_webp_by_actual_container(self):
        for fmt, mime, filename in (
            ("JPEG", "image/jpeg", "photo.jpg"),
            ("WEBP", "image/webp", "photo.webp"),
        ):
            with self.subTest(fmt=fmt):
                result = validate_reference_image(make_image(fmt), filename, mime)
                self.assertEqual(result.mime_type, mime)

    def test_rejects_signature_only_fake_png(self):
        with self.assertRaises(ValueError):
            validate_reference_image(b"\x89PNG\r\n\x1a\n" + b"x" * 20, "fake.png")

    def test_rejects_truncated_image(self):
        valid = make_image()
        with self.assertRaises(ValueError):
            validate_reference_image(valid[:24], "truncated.png")

    def test_rejects_mime_spoofing(self):
        with self.assertRaises(ValueError):
            validate_reference_image(make_image(), "fake.jpg", "image/jpeg")

    def test_rejects_unknown_and_empty(self):
        for data in (b"", b"GIF89a" + b"x" * 20, b"not-an-image"):
            with self.subTest(data=data[:8]), self.assertRaises(ValueError):
                validate_reference_image(data, "file.bin")

    def test_rejects_oversized_file(self):
        with self.assertRaises(ValueError):
            validate_reference_image(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_REFERENCE_BYTES, "large.png")

    def test_rejects_excessive_dimensions(self):
        data = make_image(size=(MAX_IMAGE_WIDTH + 1, 1))
        with self.assertRaises(ValueError):
            validate_reference_image(data, "wide.png")

    def test_rejects_excessive_pixel_count(self):
        data = make_image(size=(4000, 4001))
        self.assertGreater(4000 * 4001, MAX_IMAGE_PIXELS)
        with self.assertRaises(ValueError):
            validate_reference_image(data, "pixels.png")

    def test_rejects_animated_webp(self):
        data = make_image("WEBP", frames=2)
        with self.assertRaises(ValueError):
            validate_reference_image(data, "animated.webp")

    def test_rejects_too_many_references(self):
        one = validate_reference_image(make_image(), "one.png")
        with self.assertRaises(ValueError):
            validate_reference_batch([one] * 7)

    def test_rejects_empty_or_unvalidated_batch_items(self):
        with self.assertRaises(ValueError):
            validate_reference_batch([])
        with self.assertRaises(ValueError):
            validate_reference_batch([object()])

    def test_rejects_inconsistent_reference_size_metadata(self):
        one = validate_reference_image(make_image(), "one.png")
        with self.assertRaises(ValueError):
            validate_reference_batch([replace(one, size_bytes=999)])

    def test_accepts_bounded_batch(self):
        one = validate_reference_image(make_image(), "one.png")
        self.assertEqual(len(validate_reference_batch([one, one])), 2)


if __name__ == "__main__":
    unittest.main()
