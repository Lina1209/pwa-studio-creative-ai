"""HTTP tests for the authenticated character passport API routes."""
import unittest
from unittest.mock import patch
from app.core.config import Settings
from fastapi.testclient import TestClient
from app.main import app
from app.services.auth import StudioUser, get_current_user

OWNER = "11111111-1111-4111-8111-111111111111"
CHARACTER = "33333333-3333-4333-8333-333333333333"

class CharacterApiRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        app.dependency_overrides[get_current_user] = lambda: StudioUser(
            user_id=OWNER, email="creator@example.test", role="creator"
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.character_api.list_owned_characters", return_value=[])
    def test_list_requires_auth_and_returns_private_no_store(self, list_rows):
        response = self.client.get("/api/characters")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertEqual(response.headers["cache-control"], "private, no-store, max-age=0")

    def test_client_cannot_supply_owner_id_on_create(self):
        response = self.client.post("/api/characters", json={
            "owner_id": "22222222-2222-4222-8222-222222222222",
            "name": "Injected", "reference_data": {}
        })
        self.assertEqual(response.status_code, 422)

    def test_client_cannot_supply_owner_id_on_patch(self):
        response = self.client.patch(f"/api/characters/{CHARACTER}", json={"owner_id": OWNER})
        self.assertEqual(response.status_code, 422)

    @patch("app.character_api.create_owned_character", return_value={
        "id": CHARACTER, "source_local_id": "44444444-4444-4444-8444-444444444444", "name": "Hero", "description": None,
        "reference_data": {}, "created_at": "2026-11-27T00:00:00Z"
    })
    def test_create_binds_authenticated_owner(self, create):
        response = self.client.post("/api/characters", json={"source_local_id": "44444444-4444-4444-8444-444444444444", "name": "Hero", "reference_data": {}})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(create.call_args.args[1], OWNER)
        self.assertEqual(create.call_args.args[2], "44444444-4444-4444-8444-444444444444")

    @patch("app.character_api.update_owned_character", return_value={"id": CHARACTER, "name": "Hero", "description": "x" * 5000, "reference_data": {}, "created_at": "now", "version": 2})
    def test_patch_accepts_5000_character_description(self, update):
        response = self.client.patch(f"/api/characters/{CHARACTER}", json={"expected_version": 1, "description": "x" * 5000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(update.call_args.args[4]["description"]), 5000)

    def test_patch_rejects_description_above_local_limit(self):
        response = self.client.patch(f"/api/characters/{CHARACTER}", json={"expected_version": 1, "description": "x" * 5001})
        self.assertEqual(response.status_code, 422)

    @patch("app.services.auth.get_settings", return_value=Settings(supabase_url="https://example.supabase.co"))
    def test_guest_without_session_is_rejected(self, _settings):
        app.dependency_overrides.clear()
        response = self.client.get("/api/characters")
        self.assertEqual(response.status_code, 401)

if __name__ == "__main__":
    unittest.main()
