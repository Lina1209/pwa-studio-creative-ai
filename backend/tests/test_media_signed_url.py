"""Tests for server-only private media signed URL creation."""
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_read import MediaReadPlan
from app.services.media_signed_url import (
    SIGNED_URL_TTL_SECONDS,
    create_private_media_signed_url,
)

OWNER = "11111111-1111-4111-8111-111111111111"
RESOURCE = "22222222-2222-4222-8222-222222222222"
OBJECT = "33333333-3333-4333-8333-333333333333"


def plan():
    return MediaReadPlan(
        owner_id=OWNER,
        asset_id=OBJECT,
        bucket="studio-media",
        storage_path=f"{OWNER}/characters/{RESOURCE}/{OBJECT}.png",
    )


def settings():
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="server-secret",
    )


class MediaSignedUrlTests(unittest.TestCase):
    @patch("app.services.media_signed_url.httpx.post")
    def test_requests_fixed_short_ttl_and_returns_project_relative_link(self, post):
        response = Mock()
        response.json.return_value = {"signedURL": "/storage/v1/object/sign/studio-media/private.png?token=secret"}
        post.return_value = response

        result = create_private_media_signed_url(settings(), plan())

        self.assertEqual(
            result,
            "https://example.supabase.co/storage/v1/object/sign/studio-media/private.png?token=secret",
        )
        args, kwargs = post.call_args
        self.assertIn("/storage/v1/object/sign/studio-media/", args[0])
        self.assertEqual(kwargs["json"], {"expiresIn": SIGNED_URL_TTL_SECONDS})
        self.assertEqual(SIGNED_URL_TTL_SECONDS, 60)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer server-secret")

    @patch("app.services.media_signed_url.httpx.post")
    def test_normalizes_storage_relative_signed_path(self, post):
        response = Mock()
        response.json.return_value = {"signedURL": "/object/sign/studio-media/private.png?token=secret"}
        post.return_value = response
        result = create_private_media_signed_url(settings(), plan())
        self.assertTrue(result.startswith("https://example.supabase.co/storage/v1/object/sign/"))

    @patch("app.services.media_signed_url.httpx.post")
    def test_rejects_absolute_or_protocol_relative_returned_url(self, post):
        for signed in ("https://evil.example/steal", "//evil.example/steal", "relative/path"):
            response = Mock()
            response.json.return_value = {"signedURL": signed}
            post.return_value = response
            with self.subTest(signed=signed), self.assertRaises(HTTPException) as caught:
                create_private_media_signed_url(settings(), plan())
            self.assertEqual(caught.exception.status_code, 502)

    @patch("app.services.media_signed_url.httpx.post")
    def test_storage_error_is_sanitized(self, post):
        request = httpx.Request("POST", "https://example.supabase.co/storage")
        response = httpx.Response(403, request=request, text="secret backend detail")
        post.return_value = Mock()
        post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "secret backend detail", request=request, response=response
        )
        with self.assertRaises(HTTPException) as caught:
            create_private_media_signed_url(settings(), plan())
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("secret", caught.exception.detail)

    def test_missing_server_configuration_fails_closed(self):
        with self.assertRaises(HTTPException) as caught:
            create_private_media_signed_url(Settings(), plan())
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
