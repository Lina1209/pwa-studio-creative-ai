"""Guardrails for the private media lifecycle security contract.

These are documentation/source assertions, not API or Supabase integration tests.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "TECH_LIBRARY" / "MEDIA_ASSET_LIFECYCLE_CONTRACT.md"
MAIN = ROOT / "backend" / "app" / "main.py"


class MediaAssetLifecycleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CONTRACT.read_text(encoding="utf-8").lower()
        cls.main = MAIN.read_text(encoding="utf-8").lower()

    def test_contract_requires_server_derived_owner(self):
        self.assertIn("derive `owner_id` only from the verified jwt subject", self.contract)
        self.assertIn("ignore/reject owner ids supplied in json", self.contract)

    def test_read_sign_and_delete_resolve_database_owned_path(self):
        self.assertIn("accept a media asset uuid, not a bucket/path or url", self.contract)
        self.assertIn("resolve the immutable path from the owner's database row", self.contract)
        self.assertIn("never based solely on a client-supplied path", self.contract)

    def test_signed_urls_are_short_lived_and_never_persisted(self):
        self.assertIn("60 seconds", self.contract)
        self.assertIn("must not be placed in public profiles", self.contract)
        self.assertIn("never log", self.contract)

    def test_upload_failure_and_db_failure_have_compensation_states(self):
        for state in ("pending_upload", "object_uploaded", "ready", "upload_failed", "cleanup_pending", "deleted"):
            self.assertIn(state, self.contract)
        self.assertIn("storage and postgres do not share a transaction", self.contract)
        self.assertIn("idempotency key", self.contract)

    def test_replace_and_delete_are_idempotent_and_owner_scoped(self):
        self.assertIn("replace:", self.contract)
        self.assertIn("delete:", self.contract)
        self.assertIn("repeated requests must be idempotent", self.contract)

    def test_no_active_media_lifecycle_routes_are_claimed(self):
        self.assertNotIn("/media/upload", self.main)
        self.assertNotIn("/media/sign", self.main)
        self.assertNotIn("/media/delete", self.main)
        self.assertIn("there is no backend media upload", self.contract)

    def test_two_account_acceptance_matrix_covers_both_buckets(self):
        self.assertIn("two disposable auth accounts a and b", self.contract)
        self.assertIn("both buckets separately", self.contract)
        self.assertIn("anonymous requests cannot list or read private objects", self.contract)


if __name__ == "__main__":
    unittest.main()
