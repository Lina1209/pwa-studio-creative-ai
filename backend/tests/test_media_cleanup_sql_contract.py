"""Static guardrails for migration 0019's reference-locking and RPC boundary.

These checks complement the disposable PostgreSQL integration harness; they do
not replace real Supabase Auth/Storage integration.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase" / "migrations" / "0019_private_media_cleanup_outbox.sql"


class MediaCleanupSqlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def function_body(self, name, next_marker):
        start = self.sql.index(f"create or replace function public.{name}(")
        end = self.sql.index(next_marker, start)
        return self.sql[start:end]

    def test_character_passport_reference_locks_are_sorted(self):
        body = self.function_body(
            "pwa_guard_character_cleanup_reference",
            "drop trigger if exists characters_guard_cleanup_reference",
        )
        self.assertIn("order by a.bucket,a.storage_path", body)
        self.assertIn("pg_advisory_xact_lock", body)

    def test_media_own_and_metadata_references_share_one_sorted_lock_loop(self):
        body = self.function_body(
            "pwa_guard_media_cleanup_reference",
            "drop trigger if exists media_assets_guard_cleanup_reference",
        )
        self.assertIn("union", body)
        self.assertIn("order by refs.bucket,refs.storage_path", body)
        self.assertEqual(body.count("pg_advisory_xact_lock"), 1)
        self.assertIn("pending.status in ('cleanup_pending','deleted')", body)

    def test_cleanup_reservation_uses_the_same_global_object_order(self):
        body = self.function_body(
            "pwa_request_character_media_cleanup",
            "-- one cleanup event per claim",
        )
        self.assertIn("order by bucket,storage_path,id", body)
        self.assertIn("pg_advisory_xact_lock", body)

    def test_browser_roles_cannot_mutate_media_or_delete_characters(self):
        self.assertIn(
            "revoke insert, update, delete on public.media_assets from public, anon, authenticated",
            self.sql,
        )
        self.assertIn(
            "revoke delete on public.characters from public, anon, authenticated",
            self.sql,
        )

    def test_cleanup_rpcs_are_service_role_only(self):
        for signature in (
            "pwa_request_character_media_cleanup(uuid,uuid,uuid)",
            "pwa_claim_media_cleanup(uuid,integer)",
            "pwa_complete_media_cleanup(uuid,uuid,uuid,uuid)",
            "pwa_retry_media_cleanup(uuid,uuid,uuid,uuid,integer)",
            "pwa_finalize_character_media_cleanup(uuid,uuid)",
        ):
            self.assertIn(f"revoke all on function public.{signature}", self.sql)
            self.assertIn(f"grant execute on function public.{signature} to service_role", self.sql)


if __name__ == "__main__":
    unittest.main()
