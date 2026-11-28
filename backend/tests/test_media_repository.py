"""Tests for owner-filtered media metadata lookup; no live Supabase calls."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException

from app.core.config import Settings
from app.services import media_repository, media_upload_repository

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
ASSET = "33333333-3333-4333-8333-333333333333"
PROJECT = "44444444-4444-4444-8444-444444444444"
CHARACTER = "55555555-5555-4555-8555-555555555555"


class MediaRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(supabase_url="https://example.supabase.co",
                                 supabase_service_role_key="test-only")

    @patch("app.services.media_repository._rest_get")
    def test_asset_query_always_filters_by_asset_and_authenticated_owner(self, get):
        get.return_value = [{"id": ASSET, "owner_id": OWNER, "project_id": None,
                             "character_id": None, "storage_path": "must-not-be-returned-to-client"}]
        result = media_repository.get_owned_media_asset(self.settings, ASSET, OWNER)
        self.assertEqual(result["id"], ASSET)
        params = get.call_args.args[2]
        self.assertEqual(params["id"], f"eq.{ASSET}")
        self.assertEqual(params["owner_id"], f"eq.{OWNER}")

    @patch("app.services.media_repository._rest_get")
    def test_missing_asset_is_not_found(self, get):
        get.return_value = []
        with self.assertRaises(HTTPException) as caught:
            media_repository.get_owned_media_asset(self.settings, ASSET, OWNER)
        self.assertEqual(caught.exception.status_code, 404)

    @patch("app.services.media_repository._rest_get")
    def test_project_and_character_are_loaded_with_same_owner_filter(self, get):
        get.side_effect = [
            [{"id": ASSET, "owner_id": OWNER, "project_id": PROJECT,
              "character_id": CHARACTER}],
            [{"id": PROJECT, "owner_id": OWNER}],
            [{"id": CHARACTER, "owner_id": OWNER}],
        ]
        media_repository.get_owned_media_asset(self.settings, ASSET, OWNER)
        self.assertEqual(get.call_count, 3)
        for call in get.call_args_list[1:]:
            self.assertEqual(call.args[2]["owner_id"], f"eq.{OWNER}")

    @patch("app.services.media_repository._rest_get")
    def test_foreign_linked_project_is_hidden(self, get):
        get.side_effect = [
            [{"id": ASSET, "owner_id": OWNER, "project_id": PROJECT, "character_id": None}],
            [{"id": PROJECT, "owner_id": OTHER}],
        ]
        with self.assertRaises(HTTPException) as caught:
            media_repository.get_owned_media_asset(self.settings, ASSET, OWNER)
        self.assertEqual(caught.exception.status_code, 404)

    @patch("app.services.media_repository._rest_get")
    def test_foreign_linked_character_is_hidden(self, get):
        get.side_effect = [
            [{"id": ASSET, "owner_id": OWNER, "project_id": None, "character_id": CHARACTER}],
            [{"id": CHARACTER, "owner_id": OTHER}],
        ]
        with self.assertRaises(HTTPException) as caught:
            media_repository.get_owned_media_asset(self.settings, ASSET, OWNER)
        self.assertEqual(caught.exception.status_code, 404)

    @patch("app.services.media_repository._rest_get")
    def test_malformed_identifier_is_rejected_before_database_access(self, get):
        with self.assertRaises(HTTPException) as caught:
            media_repository.get_owned_media_asset(self.settings, "../foreign", OWNER)
        self.assertEqual(caught.exception.status_code, 422)
        get.assert_not_called()



class CharacterMediaAssetListTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="test-only")

    @patch("app.services.media_repository._rest_get")
    def test_list_filters_owner_character_bucket_and_sanitizes_fields(self, get):
        get.return_value = [{"id": ASSET, "owner_id": OWNER, "character_id": CHARACTER, "local_reference_id": "55555555-5555-4555-8555-555555555555-66666666-6666-4666-8666-666666666666", "content_sha256": "a" * 64, "file_name": "hero.png", "file_type": "image/png", "status": "ready", "size_bytes": 27, "width": 3, "height": 3, "created_at": "now", "storage_path": "secret", "bucket": "studio-media", "metadata": {"secret": True}}]
        rows = media_repository.list_owned_character_media_assets(self.settings, CHARACTER, OWNER)
        params = get.call_args.args[2]
        self.assertEqual(params["owner_id"], f"eq.{OWNER}")
        self.assertEqual(params["character_id"], f"eq.{CHARACTER}")
        self.assertEqual(params["bucket"], "eq.studio-media")
        self.assertEqual(rows[0]["status"], "ready")
        self.assertEqual(rows[0]["local_reference_id"], "55555555-5555-4555-8555-555555555555-66666666-6666-4666-8666-666666666666")
        self.assertEqual(rows[0]["content_sha256"], "a" * 64)
        for hidden in ("storage_path", "bucket", "owner_id", "metadata"): self.assertNotIn(hidden, rows[0])

    @patch("app.services.media_repository._rest_get")
    def test_list_rejects_mapped_asset_with_invalid_integrity_fingerprint(self, get):
        get.return_value = [{
            "id": ASSET, "owner_id": OWNER, "character_id": CHARACTER,
            "local_reference_id": "55555555-5555-4555-8555-555555555555-66666666-6666-4666-8666-666666666666",
            "file_name": "hero.png", "file_type": "image/png", "status": "ready",
            "size_bytes": 27, "content_sha256": "invalid", "width": 3, "height": 3,
            "created_at": "now",
        }]
        with self.assertRaises(HTTPException) as caught:
            media_repository.list_owned_character_media_assets(self.settings, CHARACTER, OWNER)
        self.assertEqual(caught.exception.status_code, 502)

    @patch("app.services.media_repository._rest_get")
    def test_list_hides_foreign_rows(self, get):
        get.return_value = [{"id": ASSET, "owner_id": OTHER, "character_id": CHARACTER, "status": "ready"}]
        with self.assertRaises(HTTPException) as caught: media_repository.list_owned_character_media_assets(self.settings, CHARACTER, OWNER)
        self.assertEqual(caught.exception.status_code, 404)

    @patch("app.services.media_repository._rest_get")
    def test_list_rejects_unknown_status(self, get):
        get.return_value = [{"id": ASSET, "owner_id": OWNER, "character_id": CHARACTER, "status": "mystery"}]
        with self.assertRaises(HTTPException) as caught: media_repository.list_owned_character_media_assets(self.settings, CHARACTER, OWNER)
        self.assertEqual(caught.exception.status_code, 502)

    @patch("app.services.media_repository._rest_get")
    def test_list_rejects_invalid_character_before_database_call(self, get):
        with self.assertRaises(HTTPException) as caught: media_repository.list_owned_character_media_assets(self.settings, "../other", OWNER)
        self.assertEqual(caught.exception.status_code, 422)
        get.assert_not_called()

    @patch("app.services.media_repository._rest_get")
    def test_list_requests_one_extra_row_and_rejects_truncated_catalog(self, get):
        get.return_value = [{}] * 101
        with self.assertRaises(HTTPException) as caught:
            media_repository.list_owned_character_media_assets(self.settings, CHARACTER, OWNER)
        self.assertEqual(caught.exception.status_code, 502)
        self.assertEqual(get.call_args.args[2]["limit"], "101")

    @patch("app.services.media_repository._rest_get")
    def test_list_rejects_duplicate_asset_ids(self, get):
        row = {
            "id": ASSET, "owner_id": OWNER, "character_id": CHARACTER,
            "status": "ready",
        }
        get.return_value = [row, row]
        with self.assertRaises(HTTPException) as caught:
            media_repository.list_owned_character_media_assets(self.settings, CHARACTER, OWNER)
        self.assertEqual(caught.exception.status_code, 502)

    @patch("app.services.media_repository._rest_get")
    def test_list_rejects_duplicate_local_reference_mapping(self, get):
        reference_id = "55555555-5555-4555-8555-555555555555-66666666-6666-4666-8666-666666666666"
        row = {
            "id": ASSET, "owner_id": OWNER, "character_id": CHARACTER,
            "local_reference_id": reference_id, "file_name": "hero.png",
            "file_type": "image/png", "status": "ready", "size_bytes": 27,
            "content_sha256": "a" * 64, "width": 3, "height": 3,
        }
        get.return_value = [row, {**row, "id": PROJECT}]
        with self.assertRaises(HTTPException) as caught:
            media_repository.list_owned_character_media_assets(self.settings, CHARACTER, OWNER)
        self.assertEqual(caught.exception.status_code, 502)

class CharacterUploadOwnershipLookupTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(supabase_url="https://example.supabase.co",
                                 supabase_service_role_key="test-only")

    @patch("app.services.media_upload_repository.httpx.get")
    def test_lookup_rejects_response_with_foreign_owner(self, get):
        get.return_value = unittest.mock.Mock(
            content=b"[]",
            json=lambda: [{"id": CHARACTER, "owner_id": OTHER}],
        )
        with self.assertRaises(HTTPException) as caught:
            media_upload_repository.get_owned_character_for_media_upload(
                self.settings, CHARACTER, OWNER
            )
        self.assertEqual(caught.exception.status_code, 404)

    @patch("app.services.media_upload_repository.httpx.get")
    def test_lookup_rejects_response_with_different_character_id(self, get):
        get.return_value = unittest.mock.Mock(
            content=b"[]",
            json=lambda: [{"id": ASSET, "owner_id": OWNER}],
        )
        with self.assertRaises(HTTPException) as caught:
            media_upload_repository.get_owned_character_for_media_upload(
                self.settings, CHARACTER, OWNER
            )
        self.assertEqual(caught.exception.status_code, 404)



class CharacterReferenceBindingRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="test-only")
        self.plan = SimpleNamespace(
            owner_id=OWNER,
            character_id=CHARACTER,
            local_reference_id="66666666-6666-4666-8666-666666666666",
            asset_id=ASSET,
            outbox_event=SimpleNamespace(id="77777777-7777-4777-8777-777777777777",
                                         idempotency_key="reference-binding-test-0001"),
            file_name="hero.png", file_type="image/png", bucket="studio-media",
            storage_path=f"{OWNER}/characters/{CHARACTER}/88888888-8888-4888-8888-888888888888.png",
            size_bytes=128, content_sha256="a" * 64, width=16, height=8,
        )

    @patch("app.services.media_upload_repository._rpc")
    def test_reservation_uses_v2_rpc_and_verifies_exact_identity_tuple(self, rpc):
        rpc.return_value = {"id": ASSET, "owner_id": OWNER, "character_id": CHARACTER,
                            "local_reference_id": self.plan.local_reference_id, "status": "pending_upload"}
        result = media_upload_repository.reserve_character_reference_upload(self.settings, self.plan)
        self.assertEqual(result["local_reference_id"], self.plan.local_reference_id)
        self.assertEqual(rpc.call_args.args[1], "pwa_reserve_character_reference_upload_v2")
        self.assertEqual(rpc.call_args.args[2]["p_local_reference_id"], self.plan.local_reference_id)

    @patch("app.services.media_upload_repository._rpc")
    def test_reservation_rejects_mismatched_local_reference_mapping(self, rpc):
        rpc.return_value = {"id": ASSET, "owner_id": OWNER, "character_id": CHARACTER,
                            "local_reference_id": "99999999-9999-4999-8999-999999999999", "status": "pending_upload"}
        with self.assertRaises(HTTPException) as caught:
            media_upload_repository.reserve_character_reference_upload(self.settings, self.plan)
        self.assertEqual(caught.exception.status_code, 502)


class CharacterMediaBulkCatalogTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="test-only")

    @patch("app.services.media_repository._rest_get")
    def test_bulk_catalog_filters_owner_and_character_set_and_returns_explicit_mapping(self, get):
        get.return_value = [{
            "id": ASSET, "owner_id": OWNER, "character_id": CHARACTER,
            "local_reference_id": "55555555-5555-4555-8555-555555555555-66666666-6666-4666-8666-666666666666",
            "file_name": "hero.png", "file_type": "image/png", "status": "ready",
            "size_bytes": 27, "content_sha256": "a" * 64, "width": 3, "height": 3,
            "created_at": "now", "bucket": "studio-media", "storage_path": "private",
            "owner_id_internal": "hidden",
        }]
        rows = media_repository.list_owned_character_media_assets_for_characters(
            self.settings, [CHARACTER, PROJECT], OWNER
        )
        params = get.call_args.args[2]
        self.assertEqual(params["owner_id"], f"eq.{OWNER}")
        self.assertEqual(params["character_id"], f"in.({CHARACTER},{PROJECT})")
        self.assertEqual(params["bucket"], "eq.studio-media")
        self.assertEqual(rows[0]["local_reference_id"], "55555555-5555-4555-8555-555555555555-66666666-6666-4666-8666-666666666666")
        self.assertEqual(rows[0]["content_sha256"], "a" * 64)
        for hidden in ("owner_id", "bucket", "storage_path", "owner_id_internal"):
            self.assertNotIn(hidden, rows[0])

    @patch("app.services.media_repository._rest_get")
    def test_bulk_catalog_rejects_duplicate_character_ids_before_database_access(self, get):
        with self.assertRaises(HTTPException) as caught:
            media_repository.list_owned_character_media_assets_for_characters(
                self.settings, [CHARACTER, CHARACTER], OWNER
            )
        self.assertEqual(caught.exception.status_code, 422)
        get.assert_not_called()

    @patch("app.services.media_repository._rest_get")
    def test_bulk_catalog_rejects_duplicate_local_reference_mapping(self, get):
        row = {
            "id": ASSET, "owner_id": OWNER, "character_id": CHARACTER,
            "local_reference_id": "55555555-5555-4555-8555-555555555555-66666666-6666-4666-8666-666666666666",
            "file_name": "hero.png", "file_type": "image/png", "status": "ready",
            "size_bytes": 27, "content_sha256": "a" * 64, "width": 3, "height": 3,
        }
        get.return_value = [row, {**row, "id": PROJECT}]
        with self.assertRaises(HTTPException) as caught:
            media_repository.list_owned_character_media_assets_for_characters(
                self.settings, [CHARACTER], OWNER
            )
        self.assertEqual(caught.exception.status_code, 502)

    @patch("app.services.media_repository._rest_get")
    def test_bulk_catalog_rejects_rows_outside_requested_owner_or_character_set(self, get):
        get.return_value = [{"id": ASSET, "owner_id": OTHER, "character_id": CHARACTER, "status": "ready"}]
        with self.assertRaises(HTTPException) as caught:
            media_repository.list_owned_character_media_assets_for_characters(
                self.settings, [CHARACTER], OWNER
            )
        self.assertEqual(caught.exception.status_code, 404)

if __name__ == "__main__":
    unittest.main()
