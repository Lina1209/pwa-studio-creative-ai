import unittest
from unittest.mock import patch, Mock
from fastapi import HTTPException
from app.services.character_repository import (
    validate_reference_data, list_owned_characters, create_owned_character,
    get_owned_character, update_owned_character,
)

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
CHARACTER = "33333333-3333-4333-8333-333333333333"

class CharacterRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.settings = Mock()
        self.settings.supabase_url = "https://example.supabase.co"
        self.settings.supabase_service_role_key = "server-secret"

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
        self.assertEqual(list_owned_characters(self.settings, OWNER), [])
        self.assertEqual(request.call_args.kwargs["params"]["owner_id"], f"eq.{OWNER}")

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

    @patch("app.services.character_repository.httpx.request")
    def test_patch_is_owner_filtered_and_allowlisted(self, request):
        request.return_value = Mock(content=b'[{"id":"%s","owner_id":"%s","name":"New","description":null,"reference_data":{},"created_at":"now"}]' % (CHARACTER.encode(), OWNER.encode()), json=lambda: [{
            "id": CHARACTER, "owner_id": OWNER, "name": "New", "description": None, "reference_data": {}, "created_at": "now"
        }])
        update_owned_character(self.settings, OWNER, CHARACTER, {"name": " New ", "owner_id": OTHER})
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["params"]["owner_id"], f"eq.{OWNER}")
        self.assertEqual(kwargs["json"], {"name": "New"})

    @patch("app.services.character_repository.httpx.request")
    def test_patch_accepts_local_ui_description_limit(self, request):
        description = "x" * 5000
        request.return_value = Mock(content=b"[]", json=lambda: [])
        with self.assertRaises(HTTPException) as caught:
            update_owned_character(self.settings, OWNER, CHARACTER, {"description": description})
        # Empty PostgREST response is a not-found result, not a validation failure.
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(request.call_args.kwargs["json"]["description"], description)

    @patch("app.services.character_repository.httpx.request")
    def test_patch_rejects_description_above_local_ui_limit(self, request):
        with self.assertRaises(HTTPException) as caught:
            update_owned_character(self.settings, OWNER, CHARACTER, {"description": "x" * 5001})
        self.assertEqual(caught.exception.status_code, 422)
        request.assert_not_called()

    def test_invalid_ids_rejected_before_database_call(self):
        with self.assertRaises(HTTPException) as caught:
            list_owned_characters(self.settings, "not-a-uuid")
        self.assertEqual(caught.exception.status_code, 422)

if __name__ == "__main__":
    unittest.main()
