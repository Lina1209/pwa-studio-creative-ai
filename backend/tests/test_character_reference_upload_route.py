"""Authenticated character-reference upload route tests; external services mocked."""
import unittest
from io import BytesIO
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services.image_reference_validation import ValidatedReference
from app.services.auth import StudioUser, get_current_user, get_platform_active_user

OWNER = "11111111-1111-4111-8111-111111111111"
CHARACTER = "22222222-2222-4222-8222-222222222222"


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (4, 3), "white").save(output, format="PNG")
    return output.getvalue()


class CharacterReferenceUploadRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: StudioUser(
            user_id=OWNER, email="creator@example.test", role="creator"
        )

        app.dependency_overrides[get_platform_active_user] = lambda: app.dependency_overrides[get_current_user]()

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.main.upload_character_reference_object")
    @patch("app.main.reserve_character_reference_upload", side_effect=HTTPException(status_code=409, detail="Media upload reservation could not be created."))
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_new_content_for_existing_local_reference_fails_closed_before_storage_upload(
        self, character_lookup, reserve, upload
    ):
        # A changed image has a new idempotency key, but migration 0025 binds
        # one immutable asset to each owner/character/local-reference tuple.
        # The reservation conflict must stop the route before any Storage write.
        changed = BytesIO()
        Image.new("RGB", (4, 3), "black").save(changed, format="PNG")
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-changed-content"},
            data={"local_reference_id": "22222222-2222-4222-8222-222222222222-44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", changed.getvalue(), "image/png")},
        )
        self.assertEqual(response.status_code, 409)
        character_lookup.assert_called_once()
        reserve.assert_called_once()
        upload.assert_not_called()

    @patch("app.main.mark_character_reference_object_uploaded", return_value={"id": "asset", "status": "object_uploaded"})
    @patch("app.main.upload_character_reference_object")
    @patch("app.main.reserve_character_reference_upload", side_effect=lambda _settings, plan: {"id": plan.asset_id, "status": "pending_upload"})
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_valid_image_uses_owner_scoped_plan_and_returns_pending_verification(
        self, character_lookup, reserve, upload, mark
    ):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0001"},
            data={"local_reference_id": "22222222-2222-4222-8222-222222222222-44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["asset"]["character_id"], CHARACTER)
        self.assertEqual(body["asset"]["local_reference_id"], "22222222-2222-4222-8222-222222222222-44444444-4444-4444-8444-444444444444")
        self.assertEqual(body["asset"]["status"], "object_uploaded")
        self.assertEqual(body["verification"], "pending")
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        self.assertNotIn("storage_path", body["asset"])
        self.assertNotIn("bucket", body["asset"])
        self.assertNotIn("owner_id", body["asset"])
        character_lookup.assert_called_once()
        reserve.assert_called_once()
        upload.assert_called_once()
        mark.assert_called_once()

    @patch("app.main.mark_character_reference_object_uploaded")
    @patch("app.main.upload_character_reference_object", side_effect=HTTPException(status_code=503, detail="storage unavailable"))
    @patch("app.main.reserve_character_reference_upload", side_effect=lambda _settings, plan: {"id": plan.asset_id, "status": "pending_upload"})
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_storage_failure_leaves_durable_reservation_for_verifier_recovery(
        self, character_lookup, reserve, upload, mark
    ):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-storage-failure"},
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 503)
        reserve.assert_called_once()
        upload.assert_called_once()
        mark.assert_not_called()

    @patch("app.main.download_private_media_image")
    @patch("app.main.mark_character_reference_object_uploaded")
    @patch("app.main.upload_character_reference_object", side_effect=HTTPException(status_code=409, detail="object already exists"))
    @patch("app.main.reserve_character_reference_upload", side_effect=lambda _settings, plan: {"id": plan.asset_id, "status": "pending_upload"})
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_duplicate_object_with_different_bytes_remains_conflict(
        self, character_lookup, reserve, upload, mark, download
    ):
        different = png_bytes() + b"different"
        image = Image.open(BytesIO(png_bytes()))
        download.return_value = ValidatedReference(
            content=different, mime_type="image/png", safe_filename="portrait.png",
            size_bytes=len(different), width=image.width, height=image.height, frame_count=1,
        )
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-different-object"},
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 409)
        upload.assert_called_once()
        download.assert_called_once()
        mark.assert_not_called()

    @patch("app.main.download_private_media_image", side_effect=HTTPException(status_code=404, detail="not found"))
    @patch("app.main.mark_character_reference_object_uploaded")
    @patch("app.main.upload_character_reference_object", side_effect=HTTPException(status_code=409, detail="object already exists"))
    @patch("app.main.reserve_character_reference_upload", return_value={"id": "asset", "status": "pending_upload"})
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_existing_unreadable_object_conflict_does_not_mark_upload(
        self, character_lookup, reserve, upload, mark, download
    ):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-object-exists"},
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 409)
        reserve.assert_called_once()
        upload.assert_called_once()
        download.assert_called_once()
        mark.assert_not_called()

    @patch("app.main.download_private_media_image")
    @patch("app.main.mark_character_reference_object_uploaded", return_value={"id": "asset", "status": "object_uploaded"})
    @patch("app.main.upload_character_reference_object", side_effect=HTTPException(status_code=409, detail="object already exists"))
    @patch("app.main.reserve_character_reference_upload", side_effect=lambda _settings, plan: {"id": plan.asset_id, "status": "pending_upload"})
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_duplicate_object_is_reconciled_only_when_exact_reserved_bytes_match(
        self, character_lookup, reserve, upload, mark, download
    ):
        content = png_bytes()
        image = Image.open(BytesIO(content))
        download.return_value = ValidatedReference(
            content=content, mime_type="image/png", safe_filename="portrait.png",
            size_bytes=len(content), width=image.width, height=image.height, frame_count=1,
        )
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-reconcile"},
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", content, "image/png")},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["asset"]["status"], "object_uploaded")
        upload.assert_called_once()
        download.assert_called_once()
        mark.assert_called_once()

    @patch("app.main.mark_character_reference_object_uploaded")
    @patch("app.main.upload_character_reference_object")
    @patch("app.main.reserve_character_reference_upload")
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_same_idempotency_key_reuses_same_asset_and_does_not_reupload_completed_object(
        self, lookup, reserve, upload, mark
    ):
        reserve.side_effect = [
            {"id": "asset", "status": "pending_upload"},
            {"id": "asset", "status": "object_uploaded"},
        ]
        mark.return_value = {"id": "asset", "status": "object_uploaded"}
        headers = {"Idempotency-Key": "test-character-upload-repeat"}
        files = {"file": ("portrait.png", png_bytes(), "image/png")}
        first = self.client.post(f"/api/characters/{CHARACTER}/references", headers=headers, data={"local_reference_id": "22222222-2222-4222-8222-222222222222-44444444-4444-4444-8444-444444444444"}, files=files)
        second = self.client.post(f"/api/characters/{CHARACTER}/references", headers=headers, data={"local_reference_id": "22222222-2222-4222-8222-222222222222-44444444-4444-4444-8444-444444444444"}, files=files)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["asset"]["id"], second.json()["asset"]["id"])
        upload.assert_called_once()
        mark.assert_called_once()

    @patch("app.main.upload_character_reference_object")
    @patch("app.main.reserve_character_reference_upload")
    @patch("app.main.get_owned_character_for_media_upload", side_effect=HTTPException(status_code=404, detail="Character not found."))
    def test_foreign_or_missing_character_is_rejected_before_reservation(self, lookup, reserve, upload):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0002"},
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 404)
        reserve.assert_not_called()
        upload.assert_not_called()

    @patch("app.main.get_owned_character_for_media_upload")
    def test_oversized_file_is_rejected_before_character_lookup(self, lookup):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0003"},
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("large.png", b"x" * (8 * 1024 * 1024 + 1), "image/png")},
        )
        self.assertEqual(response.status_code, 413)
        lookup.assert_not_called()

    @patch("app.main.get_owned_character_for_media_upload")
    def test_invalid_mime_or_image_is_rejected_before_reservation(self, lookup):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0004"},
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("fake.png", b"not an image", "image/png")},
        )
        self.assertEqual(response.status_code, 422)
        lookup.assert_called_once()

    @patch("app.main.get_owned_character_for_media_upload")
    def test_idempotency_key_is_required(self, lookup):
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 422)
        lookup.assert_not_called()

    def test_invalid_local_reference_id_is_rejected_before_reservation(self):
        with patch("app.main.get_owned_character_for_media_upload") as lookup, patch("app.main.reserve_character_reference_upload") as reserve:
            response = self.client.post(
                f"/api/characters/{CHARACTER}/references",
                headers={"Idempotency-Key": "test-character-upload-invalid-local-id"},
                data={"local_reference_id": "../foreign"},
                files={"file": ("portrait.png", png_bytes(), "image/png")},
            )
        self.assertEqual(response.status_code, 422)
        lookup.assert_called_once()
        reserve.assert_not_called()

    @patch("app.services.auth.get_settings")
    def test_missing_authentication_is_rejected(self, get_settings):
        from app.core.config import Settings
        get_settings.return_value = Settings(supabase_url="https://auth.example.test")
        app.dependency_overrides.clear()
        response = self.client.post(
            f"/api/characters/{CHARACTER}/references",
            headers={"Idempotency-Key": "test-character-upload-0005"},
            data={"local_reference_id": "44444444-4444-4444-8444-444444444444"},
            files={"file": ("portrait.png", png_bytes(), "image/png")},
        )
        self.assertEqual(response.status_code, 401)



class CharacterReferenceStatusRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.client = TestClient(app)
    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: StudioUser(user_id=OWNER, email="creator@example.test", role="creator")
        app.dependency_overrides[get_platform_active_user] = lambda: app.dependency_overrides[get_current_user]()

        app.dependency_overrides[get_platform_active_user] = lambda: app.dependency_overrides[get_current_user]()
    def tearDown(self): app.dependency_overrides.clear()

    @patch("app.main.list_owned_character_media_assets", return_value=[{"id": "33333333-3333-4333-8333-333333333333", "character_id": CHARACTER, "local_reference_id": "44444444-4444-4444-8444-444444444444", "content_sha256": "a" * 64, "file_name": "hero.png", "file_type": "image/png", "status": "object_uploaded", "size_bytes": 27, "width": 3, "height": 3, "created_at": "now"}])
    @patch("app.main.get_owned_character_for_media_upload", return_value={"id": CHARACTER, "owner_id": OWNER})
    def test_status_list_is_owner_checked_private_and_no_store(self, character, assets):
        response = self.client.get(f"/api/characters/{CHARACTER}/references")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["status"], "object_uploaded")
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        for hidden in ("storage_path", "bucket", "owner_id"): self.assertNotIn(hidden, response.text)
        character.assert_called_once(); assets.assert_called_once()
        self.assertEqual(assets.call_args.args[2], OWNER)

    @patch("app.main.list_owned_character_media_assets")
    @patch("app.main.get_owned_character_for_media_upload", side_effect=HTTPException(status_code=404, detail="Character not found."))
    def test_foreign_character_cannot_list_upload_states(self, character, assets):
        response = self.client.get(f"/api/characters/{CHARACTER}/references")
        self.assertEqual(response.status_code, 404)
        assets.assert_not_called()



class CharacterReferenceBulkCatalogRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: StudioUser(
            user_id=OWNER, email="creator@example.test", role="creator"
        )

        app.dependency_overrides[get_platform_active_user] = lambda: app.dependency_overrides[get_current_user]()

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.main.list_owned_character_media_assets_for_characters", return_value=[
        {"id": "33333333-3333-4333-8333-333333333333", "character_id": CHARACTER,
         "local_reference_id": CHARACTER + "-44444444-4444-4444-8444-444444444444",
         "status": "ready", "content_sha256": "a" * 64}
    ])
    def test_bulk_catalog_is_authenticated_private_and_no_store(self, catalog):
        response = self.client.get(
            f"/api/media/character-references?character_ids={CHARACTER}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["local_reference_id"],
                         CHARACTER + "-44444444-4444-4444-8444-444444444444")
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")
        catalog.assert_called_once()
        self.assertEqual(catalog.call_args.args[1], [CHARACTER])
        self.assertEqual(catalog.call_args.args[2], OWNER)

    @patch("app.main.list_owned_character_media_assets_for_characters")
    def test_bulk_catalog_rejects_more_than_100_character_ids(self, catalog):
        ids = ",".join([CHARACTER] * 101)
        response = self.client.get(f"/api/characters/references?character_ids={ids}")
        self.assertEqual(response.status_code, 422)
        catalog.assert_not_called()


if __name__ == "__main__":
    unittest.main()
