import unittest
from unittest.mock import patch, Mock
from fastapi import HTTPException
from app.services.character_repository import (
    validate_reference_data, list_owned_characters, create_owned_character,
    get_owned_character, update_owned_character, _encode_cursor,
)

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
CHARACTER = "33333333-3333-4333-8333-333333333333"

class CharacterRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.settings = Mock()
        self.settings.supabase_url = "https://example.supabase.co"
        self.settings.supabase_service_role_key = "server-secret-key-material-long-enough"

    def test_reference_data_requires_json_object(self):
        with self.assertRaises(HTTPException):
            validate_reference_data(["not", "an", "object"])

    def test_reference_data_enforces_size_depth_and_field_limits(self):
        with self.assertRaises(HTTPException):
            validate_reference_data({"bio": "x" * 25000})
        nested = {"a": {"b": {"c": {"d": {"e": {"f": {"g": "deep"}}}}}}}
        with self.assertRaises(HTTPException):
            validate_reference_data(nested)
        with self.assertRaises(HTTPException):
            validate_reference_data({"items": list(range(101))})

    def test_valid_reference_data_is_preserved(self):
        data = {"appearance": {"hair": "red"}, "tags": ["hero", "fantasy"]}
        self.assertEqual(validate_reference_data(data), data)

    @patch("app.services.character_repository.httpx.request")
    def test_list_filters_by_authenticated_owner_and_never_returns_other_rows(self, request):
        request.return_value = Mock(content=b"[]", json=lambda: [])
        self.assertEqual(list_owned_characters(self.settings, OWNER)["items"], [])
        self.assertEqual(request.call_args.kwargs["params"]["owner_id"], f"eq.{OWNER}")

    @patch("app.services.character_repository.httpx.request")
    def test_list_rejects_unexpected_foreign_row_even_if_query_was_owner_filtered(self, request):
        request.return_value = Mock(content=b"[]", json=lambda: [{
            "id": CHARACTER, "owner_id": OTHER, "source_local_id": CHARACTER,
            "name": "Foreign", "description": None, "reference_data": {}, "created_at": "now"
        }])
        with self.assertRaises(HTTPException) as caught:
            list_owned_characters(self.settings, OWNER)
        self.assertEqual(caught.exception.status_code, 404)

    @patch("app.services.character_repository.httpx.request")
    def test_list_returns_bounded_page_and_signed_next_cursor(self, request):
        rows = [
            {"id": CHARACTER, "owner_id": OWNER, "source_local_id": CHARACTER,
             "name": "One", "description": None, "reference_data": {}, "created_at": "2026-01-02T00:00:00Z", "version": 1},
            {"id": "44444444-4444-4444-8444-444444444444", "owner_id": OWNER, "source_local_id": CHARACTER,
             "name": "Two", "description": None, "reference_data": {}, "created_at": "2026-01-01T00:00:00Z", "version": 1},
        ]
        request.return_value = Mock(content=b"[]", json=lambda: rows)
        page = list_owned_characters(self.settings, OWNER, page_size=1)
        self.assertEqual(len(page["items"]), 1)
        self.assertIsNotNone(page["next_cursor"])
        params = request.call_args.kwargs["params"]
        self.assertEqual(params["limit"], "2")
        self.assertEqual(params["order"], "created_at.desc,id.desc")
        self.assertIn("created_at", params)

    @patch("app.services.character_repository.httpx.request")
    def test_list_uses_signed_cursor_for_keyset_next_page(self, request):
        cursor = _encode_cursor(self.settings, {
            "owner": OWNER, "snapshot": "2026-01-03T00:00:00Z",
            "last_created_at": "2026-01-02T00:00:00Z", "last_id": CHARACTER,
            "expires": 4102444800,
        })
        request.return_value = Mock(content=b"[]", json=lambda: [])
        page = list_owned_characters(self.settings, OWNER, cursor=cursor, page_size=25)
        self.assertEqual(page["items"], [])
        params = request.call_args.kwargs["params"]
        self.assertEqual(params["limit"], "26")
        self.assertIn("created_at.lt.2026-01-02T00:00:00Z", params["or"])
        self.assertIn("id.lt."+CHARACTER, params["or"])

    def test_list_rejects_tampered_or_foreign_cursor(self):
        token = _encode_cursor(self.settings, {
            "owner": OWNER, "snapshot": "2026-01-03T00:00:00Z",
            "last_created_at": "2026-01-02T00:00:00Z", "last_id": CHARACTER,
            "expires": 4102444800,
        })
        with self.assertRaises(HTTPException) as caught:
            list_owned_characters(self.settings, OWNER, cursor=token[:-1] + ("A" if token[-1] != "A" else "B"))
        self.assertEqual(caught.exception.status_code, 422)
        foreign = _encode_cursor(self.settings, {
            "owner": OTHER, "snapshot": "2026-01-03T00:00:00Z",
            "last_created_at": "2026-01-02T00:00:00Z", "last_id": CHARACTER,
            "expires": 4102444800,
        })
        with self.assertRaises(HTTPException) as caught:
            list_owned_characters(self.settings, OWNER, cursor=foreign)
        self.assertEqual(caught.exception.status_code, 422)

    def test_list_rejects_invalid_page_size(self):
        for size in (0, 101, True, 1.5):
            with self.subTest(size=size):
                with self.assertRaises(HTTPException) as caught:
                    list_owned_characters(self.settings, OWNER, page_size=size)
                self.assertEqual(caught.exception.status_code, 422)

    @patch("app.services.character_repository.httpx.post")
    def test_create_uses_verified_owner_and_stable_local_mapping(self, request):
        local_id = "44444444-4444-4444-8444-444444444444"
        request.return_value = Mock(content=b"{}", json=lambda: {
            "id": CHARACTER, "owner_id": OWNER, "source_local_id": local_id,
            "name": "Lina", "description": None, "reference_data": {}, "created_at": "now"
        })
        row = create_owned_character(self.settings, OWNER, local_id, " Lina ", None, {})
        payload = request.call_args.kwargs["json"]
        self.assertEqual(payload["p_owner_id"], OWNER)
        self.assertEqual(payload["p_source_local_id"], local_id)
        self.assertEqual(payload["p_name"], "Lina")
        self.assertEqual(row["source_local_id"], local_id)
        self.assertNotIn("avatar_url", row)
        self.assertNotIn("owner_id", row)

    @patch("app.services.character_repository.httpx.request")
    def test_foreign_character_is_hidden_as_not_found(self, request):
        request.return_value = Mock(content=b"[]", json=lambda: [])
        with self.assertRaises(HTTPException) as caught:
            get_owned_character(self.settings, OWNER, CHARACTER)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(request.call_args.kwargs["params"]["owner_id"], f"eq.{OWNER}")

    @patch("app.services.character_repository._rpc")
    def test_patch_uses_versioned_rpc_and_allowlists_fields(self, rpc):
        rpc.return_value = {
            "id": CHARACTER, "owner_id": OWNER, "source_local_id": CHARACTER,
            "name": "New", "description": None, "reference_data": {},
            "created_at": "now", "version": 2
        }
        row = update_owned_character(self.settings, OWNER, CHARACTER, 1,
                                     {"name": " New ", "owner_id": OTHER})
        self.assertEqual(rpc.call_args.args[1], "pwa_update_character_versioned")
        payload = rpc.call_args.args[2]
        self.assertEqual(payload["p_owner_id"], OWNER)
        self.assertEqual(payload["p_character_id"], CHARACTER)
        self.assertEqual(payload["p_expected_version"], 1)
        self.assertEqual(payload["p_changes"], {"name": "New"})
        self.assertEqual(row["version"], 2)

    @patch("app.services.character_repository._rpc")
    def test_patch_stale_version_returns_conflict_without_retry(self, rpc):
        rpc.return_value = {"conflict": True, "version": 3}
        with self.assertRaises(HTTPException) as caught:
            update_owned_character(self.settings, OWNER, CHARACTER, 2, {"name": "Stale"})
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "character_version_conflict")
        rpc.assert_called_once()

    @patch("app.services.character_repository._rpc")
    def test_patch_foreign_or_missing_character_returns_not_found(self, rpc):
        rpc.return_value = {"not_found": True}
        with self.assertRaises(HTTPException) as caught:
            update_owned_character(self.settings, OWNER, CHARACTER, 1, {"name": "Nope"})
        self.assertEqual(caught.exception.status_code, 404)

    @patch("app.services.character_repository._rpc")
    def test_patch_requires_positive_integer_version(self, rpc):
        for value in (0, -1, True, 1.5, "1"):
            with self.subTest(value=value):
                with self.assertRaises(HTTPException) as caught:
                    update_owned_character(self.settings, OWNER, CHARACTER, value, {"name": "Nope"})
                self.assertEqual(caught.exception.status_code, 422)
        rpc.assert_not_called()

    @patch("app.services.character_repository._rpc")
    def test_patch_rejects_invalid_returned_version(self, rpc):
        rpc.return_value = {
            "id": CHARACTER, "owner_id": OWNER, "name": "New",
            "description": None, "reference_data": {}, "created_at": "now", "version": 8
        }
        with self.assertRaises(HTTPException) as caught:
            update_owned_character(self.settings, OWNER, CHARACTER, 1, {"name": "New"})
        self.assertEqual(caught.exception.status_code, 502)

    def test_invalid_ids_rejected_before_database_call(self):
        with self.assertRaises(HTTPException) as caught:
            list_owned_characters(self.settings, "not-a-uuid")
        self.assertEqual(caught.exception.status_code, 422)

if __name__ == "__main__":
    unittest.main()
