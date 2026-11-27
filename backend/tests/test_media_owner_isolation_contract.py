"""Static owner-isolation contract checks for the draft Supabase schema.

These tests inspect SQL source only. They do not execute Postgres RLS or Storage
requests and must not be described as a live cross-account security test.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_0012 = ROOT / "supabase" / "migrations" / "0012_character_library_media_links.sql"
MIGRATION_0017 = ROOT / "supabase" / "migrations" / "0017_owner_scoped_media_associations.sql"
PROJECTS = ROOT / "supabase" / "migrations" / "0005_cloud_projects_and_storage.sql"
STORAGE_BASE = ROOT / "supabase" / "migrations" / "0002_storage_and_moderation.sql"
DIAGNOSTIC = ROOT / "supabase" / "diagnostics" / "inspect_cloud_storage.sql"


class MediaOwnerIsolationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.character_sql = MIGRATION_0012.read_text(encoding="utf-8")
        cls.hardening_sql = MIGRATION_0017.read_text(encoding="utf-8")
        cls.project_sql = PROJECTS.read_text(encoding="utf-8")
        cls.storage_sql = STORAGE_BASE.read_text(encoding="utf-8")
        cls.diagnostic_sql = DIAGNOSTIC.read_text(encoding="utf-8")

    def test_projects_are_owner_scoped_with_using_and_check(self):
        self.assertIn("alter table public.projects enable row level security", self.project_sql.lower())
        policy = self.project_sql.split('create policy "Users manage own studio projects"', 1)[1]
        self.assertIn("using (auth.uid() = owner_id)", policy)
        self.assertIn("with check (auth.uid() = owner_id)", policy)

    def test_character_and_media_rows_are_owner_scoped(self):
        self.assertIn("alter table public.characters enable row level security", self.character_sql.lower())
        self.assertIn("alter table public.media_assets enable row level security", self.character_sql.lower())
        self.assertIn("using (owner_id = auth.uid())", self.character_sql)
        self.assertIn("with check (owner_id = auth.uid())", self.character_sql)

    def test_character_media_link_has_composite_owner_foreign_key(self):
        self.assertIn("foreign key (character_id, owner_id)", self.character_sql.lower())
        self.assertIn("references public.characters (id, owner_id)", self.character_sql.lower())

    def test_project_media_link_has_composite_owner_foreign_key(self):
        self.assertIn("unique (id, owner_id)", self.hardening_sql.lower())
        self.assertIn("foreign key (project_id, owner_id)", self.hardening_sql.lower())
        self.assertIn("references public.projects (id, owner_id)", self.hardening_sql.lower())
        self.assertIn("on delete set null (project_id)", self.hardening_sql.lower())

    def test_hardening_recreates_owner_policies_instead_of_trusting_policy_name(self):
        for table, policy in (("characters", "characters_owner"), ("media_assets", "media_assets_owner")):
            self.assertIn(f"drop policy if exists {policy} on public.{table}", self.hardening_sql)
            self.assertIn(f"create policy {policy} on public.{table}", self.hardening_sql)
        self.assertEqual(self.hardening_sql.lower().count("using (owner_id = (select auth.uid()))"), 2)
        self.assertEqual(self.hardening_sql.lower().count("with check (owner_id = (select auth.uid()))"), 2)

    def test_storage_buckets_are_private_and_paths_are_owner_scoped(self):
        self.assertIn("'studio-media', 'studio-media', false", self.storage_sql)
        self.assertIn("'studio-exports', 'studio-exports', false", self.storage_sql)
        for action in ("select", "insert", "update", "delete"):
            self.assertIn(f"for {action} to authenticated", self.hardening_sql.lower())
        self.assertEqual(self.hardening_sql.count("(storage.foldername(name))[1] = (select auth.uid())::text"), 5)
        self.assertEqual(self.hardening_sql.count("bucket_id in ('studio-media', 'studio-exports')"), 4)

    def test_diagnostic_inspects_all_effective_policies_and_foreign_keys(self):
        self.assertIn("pg_policies", self.diagnostic_sql)
        self.assertIn("pg_constraint", self.diagnostic_sql)
        self.assertIn("information_schema.role_table_grants", self.diagnostic_sql)


if __name__ == "__main__":
    unittest.main()
