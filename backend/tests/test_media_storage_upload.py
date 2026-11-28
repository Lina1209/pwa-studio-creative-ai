"""Private Storage upload primitive tests; all network calls are mocked."""
import unittest
from io import BytesIO
from uuid import uuid4
from unittest.mock import Mock, patch

from PIL import Image
from fastapi import HTTPException

from app.core.config import Settings
from app.services.media_workflow import plan_character_reference_upload
from app.services.media_storage_upload import upload_character_reference_object

OWNER = "11111111-1111-4111-8111-111111111111"
CHARACTER = "22222222-2222-4222-8222-222222222222"


def png():
    output = BytesIO()
    Image.new("RGB", (3, 2), "white").save(output, format="PNG")
    return output.getvalue()


def settings():
    return Settings(supabase_url="https://example.supabase.co",
                    supabase_service_role_key="eyJserver.only-secret")


def upload_plan():
    content = png()
    return plan_character_reference_upload(
        authenticated_owner_id=OWNER,
        character={"id": CHARACTER, "owner_id": OWNER},
        asset_id=str(uuid4()), object_id=str(uuid4()), event_id=str(uuid4()),
        idempotency_key="character-reference-upload-01",
        local_reference_id=CHARACTER + "-66666666-6666-4666-8666-666666666666",
        content=content, filename="hero.png", declared_mime_type="image/png",
    ), content


class MediaStorageUploadTests(unittest.TestCase):
    @patch("app.services.media_storage_upload.httpx.post")
    def test_upload_uses_server_planned_private_key_and_no_upsert(self, post):
        plan, content = upload_plan()
        post.return_value = Mock(status_code=200)
        upload_character_reference_object(settings(), plan, content)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://example.supabase.co/storage/v1/object/studio-media/" + plan.storage_path)
        self.assertEqual(kwargs["content"], content)
        self.assertEqual(kwargs["headers"]["x-upsert"], "false")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer eyJserver.only-secret")

    @patch("app.services.media_storage_upload.httpx.post")
    def test_rejects_content_length_mismatch_before_network(self, post):
        plan, content = upload_plan()
        with self.assertRaises(HTTPException) as caught:
            upload_character_reference_object(settings(), plan, content + b"x")
        self.assertEqual(caught.exception.status_code, 400)
        post.assert_not_called()

    @patch("app.services.media_storage_upload.httpx.post")
    def test_rejects_same_size_bytes_with_different_digest(self, post):
        plan, content = upload_plan()
        altered = bytes([content[0] ^ 1]) + content[1:]
        self.assertEqual(len(altered), len(content))
        with self.assertRaises(HTTPException) as caught:
            upload_character_reference_object(settings(), plan, altered)
        self.assertEqual(caught.exception.status_code, 400)
        post.assert_not_called()

    @patch("app.services.media_storage_upload.httpx.post")
    def test_duplicate_object_is_conflict_and_never_overwritten(self, post):
        plan, content = upload_plan()
        post.return_value = Mock(status_code=409)
        with self.assertRaises(HTTPException) as caught:
            upload_character_reference_object(settings(), plan, content)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(post.call_args.kwargs["headers"]["x-upsert"], "false")

    def test_missing_server_credentials_fails_closed(self):
        plan, content = upload_plan()
        with self.assertRaises(HTTPException) as caught:
            upload_character_reference_object(
                Settings(supabase_url="https://example.supabase.co"), plan, content
            )
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
