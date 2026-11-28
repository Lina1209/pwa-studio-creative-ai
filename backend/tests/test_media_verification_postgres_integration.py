"""Worker-to-PostgreSQL integration test using disposable CI PostgreSQL.

The database RPCs and worker state transition are real. Only the Storage HTTP
transport is simulated; no Supabase project or external service is contacted.
Run with DISPOSABLE_DATABASE_URL and PWA_TEST_OWNER_ID set.
"""
import hashlib
import json
import os
import subprocess
import unittest
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from app.core.config import Settings
from app.workers.media_outbox_worker import process_one


DATABASE_URL = os.environ.get("DISPOSABLE_DATABASE_URL")
OWNER_ID = os.environ.get("PWA_TEST_OWNER_ID")


@unittest.skipUnless(DATABASE_URL and OWNER_ID, "requires disposable PostgreSQL CI environment")
class MediaVerificationPostgresIntegrationTests(unittest.TestCase):
    def psql_json(self, sql):
        result = subprocess.run(
            [
                "psql", DATABASE_URL, "-X", "-qAt",
                "-v", "ON_ERROR_STOP=1", "-c", sql,
            ],
            check=True, capture_output=True, text=True, timeout=20,
        )
        return json.loads(result.stdout.strip())

    def psql_text(self, sql):
        result = subprocess.run(
            [
                "psql", DATABASE_URL, "-X", "-qAt",
                "-v", "ON_ERROR_STOP=1", "-c", sql,
            ],
            check=True, capture_output=True, text=True, timeout=20,
        )
        return result.stdout.strip()

    def test_real_worker_claim_decode_and_database_ready_transition(self):
        character_id = self.psql_text(
            "insert into public.characters(owner_id,name,reference_data) "
            f"values ('{OWNER_ID}'::uuid,'Worker integration fixture','{{}}'::jsonb) "
            "returning id"
        )
        asset_id, operation_id, event_id, object_id = (str(uuid4()) for _ in range(4))
        buffer = BytesIO()
        Image.new("RGB", (5, 4), (23, 45, 67)).save(buffer, format="PNG")
        png = buffer.getvalue()
        digest = hashlib.sha256(png).hexdigest()
        storage_path = f"{OWNER_ID}/characters/{character_id}/{object_id}.png"
        idempotency = f"worker-e2e-{event_id}"

        reservation = (
            "select public.pwa_reserve_character_reference_upload("
            f"'{OWNER_ID}'::uuid,'{character_id}'::uuid,'{asset_id}'::uuid,"
            f"'{operation_id}'::uuid,'{event_id}'::uuid,'{idempotency}',"
            "'integration.png','image/png','studio-media',"
            f"'{storage_path}',{len(png)},'{digest}',5,4)"
        )
        self.psql_json(reservation)
        self.psql_json(
            "select public.pwa_mark_character_reference_object_uploaded("
            f"'{OWNER_ID}'::uuid,'{asset_id}'::uuid,'{operation_id}'::uuid)"
        )

        def claim(_settings, claim_token, lease_seconds):
            return self.psql_json(
                "select public.pwa_claim_media_upload_verification("
                f"'{claim_token}'::uuid,{int(lease_seconds)})"
            )

        def complete(_settings, event, verified):
            actual_digest = hashlib.sha256(verified.content).hexdigest()
            return self.psql_json(
                "select public.pwa_complete_media_upload_verification("
                f"'{event['owner_id']}'::uuid,'{event['asset_id']}'::uuid,"
                f"'{event['event_id']}'::uuid,'{event['claim_token']}'::uuid,"
                f"'{actual_digest}',{verified.size_bytes},'{verified.mime_type}',"
                f"{verified.width},{verified.height})"
            )

        settings = Settings(
            supabase_url="https://storage.example.invalid",
            supabase_service_role_key="disposable-test-only",
        )

        with patch(
            "app.workers.media_outbox_worker.claim_media_upload_verification",
            side_effect=claim,
        ), patch(
            "app.workers.media_outbox_worker.complete_media_upload_verification",
            side_effect=complete,
        ), patch("app.services.media_content.httpx.stream") as stream:
            response = stream.return_value.__enter__.return_value
            response.headers = {"content-length": str(len(png))}
            response.iter_bytes.return_value = iter([png])
            response.raise_for_status.return_value = None

            self.assertTrue(process_one(settings))

        self.assertEqual(
            self.psql_text(f"select status from public.media_assets where id='{asset_id}'::uuid"),
            "ready",
        )
        self.assertEqual(
            self.psql_text(
                "select status from public.media_asset_outbox "
                f"where id='{event_id}'::uuid"
            ),
            "delivered",
        )
        self.assertEqual(
            stream.call_args.args[1],
            "https://storage.example.invalid/storage/v1/object/studio-media/" + storage_path,
        )


if __name__ == "__main__":
    unittest.main()
