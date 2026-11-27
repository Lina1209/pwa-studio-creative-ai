"""Tests for owner-filtered media metadata lookup; no live Supabase calls."""
import unittest
from unittest.mock import patch
from fastapi import HTTPException

from app.core.config import Settings
from app.services import media_repository

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


if __name__ == "__main__":
    unittest.main()
