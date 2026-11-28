"""Bounded private image download tests; no real Storage calls."""
import unittest
from contextlib import nullcontext
from io import BytesIO
from unittest.mock import Mock, patch

from fastapi import HTTPException
from PIL import Image

from app.core.config import Settings
from app.services.image_reference_validation import MAX_REFERENCE_BYTES
from app.services.media_content import download_private_media_image
from app.services.media_read import MediaReadPlan

OWNER = "11111111-1111-4111-8111-111111111111"
RESOURCE = "22222222-2222-4222-8222-222222222222"
OBJECT = "33333333-3333-4333-8333-333333333333"


def settings():
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="eyJserver.secret",
    )


def plan():
    return MediaReadPlan(
        owner_id=OWNER, asset_id=OBJECT, bucket="studio-media",
        storage_path=f"{OWNER}/characters/{RESOURCE}/{OBJECT}.png",
    )


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (2, 2), "white").save(output, format="PNG")
    return output.getvalue()


class MediaContentTests(unittest.TestCase):
    @patch("app.services.media_content.httpx.stream")
    def test_downloads_from_server_path_and_fully_validates_image(self, stream):
        response = Mock()
        response.headers = {"content-length": str(len(png_bytes()))}
        response.iter_bytes.return_value = [png_bytes()]
        stream.return_value = nullcontext(response)

        result = download_private_media_image(
            settings(), plan(), file_name="portrait.png",
            expected_mime_type="image/png",
        )
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual((result.width, result.height), (2, 2))
        args, kwargs = stream.call_args
        self.assertEqual(args[0], "GET")
        self.assertIn("/storage/v1/object/studio-media/", args[1])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer eyJserver.secret")

    @patch("app.services.media_content.httpx.stream")
    def test_modern_secret_key_is_apikey_only(self, stream):
        response = Mock()
        response.headers = {"content-length": str(len(png_bytes()))}
        response.iter_bytes.return_value = [png_bytes()]
        stream.return_value = nullcontext(response)
        modern = Settings(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="sb_secret_test_only",
        )
        download_private_media_image(
            modern, plan(), file_name="portrait.png",
            expected_mime_type="image/png",
        )
        headers = stream.call_args.kwargs["headers"]
        self.assertEqual(headers["apikey"], "sb_secret_test_only")
        self.assertNotIn("Authorization", headers)

    @patch("app.services.media_content.httpx.stream")
    def test_rejects_declared_oversized_object_before_reading(self, stream):
        response = Mock()
        response.headers = {"content-length": str(MAX_REFERENCE_BYTES + 1)}
        stream.return_value = nullcontext(response)
        with self.assertRaises(HTTPException) as caught:
            download_private_media_image(
                settings(), plan(), file_name="portrait.png",
                expected_mime_type="image/png",
            )
        self.assertEqual(caught.exception.status_code, 413)
        response.iter_bytes.assert_not_called()

    @patch("app.services.media_content.httpx.stream")
    def test_rejects_stream_that_exceeds_limit(self, stream):
        response = Mock()
        response.headers = {}
        response.iter_bytes.return_value = [b"x" * (MAX_REFERENCE_BYTES + 1)]
        stream.return_value = nullcontext(response)
        with self.assertRaises(HTTPException) as caught:
            download_private_media_image(
                settings(), plan(), file_name="portrait.png",
                expected_mime_type="image/png",
            )
        self.assertEqual(caught.exception.status_code, 413)

    def test_rejects_non_image_mime_without_storage_request(self):
        with patch("app.services.media_content.httpx.stream") as stream:
            with self.assertRaises(HTTPException) as caught:
                download_private_media_image(
                    settings(), plan(), file_name="movie.mp4",
                    expected_mime_type="video/mp4",
                )
        self.assertEqual(caught.exception.status_code, 404)
        stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
