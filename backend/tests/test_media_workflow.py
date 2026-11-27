"""Composition tests for the private character-reference upload boundary."""
import unittest
import hashlib
from io import BytesIO
from uuid import uuid4

from PIL import Image
from fastapi import HTTPException

from app.services.media_lifecycle import MediaStatus
from app.services.media_outbox import OutboxStatus
from app.services.media_workflow import plan_character_reference_upload

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
CHARACTER = "33333333-3333-4333-8333-333333333333"


def png():
    output = BytesIO()
    Image.new("RGB", (20, 12), (40, 80, 120)).save(output, format="PNG")
    return output.getvalue()


def plan(**overrides):
    values = dict(
        authenticated_owner_id=OWNER,
        character={"id": CHARACTER, "owner_id": OWNER},
        asset_id=str(uuid4()), object_id=str(uuid4()), event_id=str(uuid4()),
        idempotency_key="character-ref-upload-0001",
        content=png(), filename="../../hero.png", declared_mime_type="image/png",
    )
    values.update(overrides)
    return plan_character_reference_upload(**values)


class CharacterReferenceWorkflowTests(unittest.TestCase):
    def test_composes_owner_validation_image_validation_and_outbox_plan(self):
        result = plan()
        self.assertEqual(result.owner_id, OWNER)
        self.assertEqual(result.character_id, CHARACTER)
        self.assertEqual(result.initial_status, MediaStatus.PENDING_UPLOAD)
        self.assertEqual(result.outbox_event.status, OutboxStatus.PENDING)
        self.assertEqual(result.outbox_event.event_type, "media_upload_verify_requested")
        self.assertEqual(result.file_name, "hero.png")
        self.assertEqual(result.file_type, "image/png")
        self.assertEqual(result.content_sha256, hashlib.sha256(png()).hexdigest())
        self.assertEqual(result.storage_path.split("/")[0], OWNER)
        self.assertEqual(result.storage_path.split("/")[1], "characters")
        self.assertNotIn("..", result.storage_path)

    def test_foreign_character_is_rejected_before_planning(self):
        with self.assertRaises(HTTPException) as caught:
            plan(character={"id": CHARACTER, "owner_id": OTHER})
        self.assertEqual(caught.exception.status_code, 404)

    def test_client_cannot_choose_public_bucket(self):
        with self.assertRaises(HTTPException):
            plan(bucket="public")

    def test_mime_spoofing_is_rejected(self):
        with self.assertRaises(ValueError):
            plan(declared_mime_type="image/jpeg")

    def test_invalid_image_bytes_are_rejected(self):
        with self.assertRaises(ValueError):
            plan(content=b"not an image")

    def test_outbox_event_is_bound_to_the_asset_id(self):
        result = plan()
        self.assertEqual(result.outbox_event.asset_id, result.asset_id)

    def test_missing_character_is_rejected(self):
        with self.assertRaises(ValueError):
            plan(character=None)


if __name__ == "__main__":
    unittest.main()
