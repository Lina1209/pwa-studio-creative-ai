import unittest

from app.services.image_reference_validation import (
    MAX_REFERENCE_BYTES,
    validate_reference_batch,
    validate_reference_image,
)


class ImageReferenceValidationTests(unittest.TestCase):
    def test_accepts_png_by_signature(self):
        result = validate_reference_image(b"\x89PNG\r\n\x1a\n" + b"x" * 20, "../../portrait.png", "image/png")
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual(result.safe_filename, "portrait.png")

    def test_accepts_webp_by_container_signature(self):
        data = b"RIFF" + (20).to_bytes(4, "little") + b"WEBP" + b"x" * 8
        self.assertEqual(validate_reference_image(data, "ref.webp").mime_type, "image/webp")

    def test_rejects_mime_spoofing(self):
        with self.assertRaises(ValueError):
            validate_reference_image(b"\x89PNG\r\n\x1a\n" + b"x", "fake.jpg", "image/jpeg")

    def test_rejects_unknown_and_empty(self):
        for data in (b"", b"GIF89a" + b"x" * 20, b"not-an-image"):
            with self.subTest(data=data[:8]), self.assertRaises(ValueError):
                validate_reference_image(data, "file.bin")

    def test_rejects_oversized_file(self):
        with self.assertRaises(ValueError):
            validate_reference_image(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_REFERENCE_BYTES, "large.png")

    def test_rejects_too_many_references(self):
        one = validate_reference_image(b"\x89PNG\r\n\x1a\n" + b"x", "one.png")
        with self.assertRaises(ValueError):
            validate_reference_batch([one] * 7)

    def test_rejects_empty_or_unvalidated_batch_items(self):
        with self.assertRaises(ValueError):
            validate_reference_batch([])
        with self.assertRaises(ValueError):
            validate_reference_batch([object()])

    def test_rejects_inconsistent_reference_size_metadata(self):
        from dataclasses import replace

        one = validate_reference_image(b"\\x89PNG\\r\\n\\x1a\\n" + b"x", "one.png")
        with self.assertRaises(ValueError):
            validate_reference_batch([replace(one, size_bytes=999)])

    def test_accepts_bounded_batch(self):
        one = validate_reference_image(b"\x89PNG\r\n\x1a\n" + b"x", "one.png")
        self.assertEqual(len(validate_reference_batch([one, one])), 2)


if __name__ == "__main__":
    unittest.main()
