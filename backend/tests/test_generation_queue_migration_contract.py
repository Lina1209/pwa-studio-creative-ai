"""Static guardrails for the draft SQL queue contract.

These tests inspect source only. They do not parse/execute PostgreSQL or prove
transaction isolation, permissions in a live Supabase project, or race safety.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
BASE_MIGRATION = ROOT / "supabase" / "migrations" / "0013_generation_jobs_and_outbox.sql"
MIGRATION = ROOT / "supabase" / "migrations" / "0014_generation_job_queue_rpcs.sql"
PREFLIGHT = ROOT / "supabase" / "tests" / "0014_generation_job_rpcs_preflight.sql"
BEHAVIOR = ROOT / "supabase" / "tests" / "0015_generation_job_queue_behavior.sql"


class GenerationQueueMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_sql = BASE_MIGRATION.read_text(encoding="utf-8")
        cls.sql = MIGRATION.read_text(encoding="utf-8")
        cls.preflight = PREFLIGHT.read_text(encoding="utf-8")
        cls.behavior = BEHAVIOR.read_text(encoding="utf-8")

    def test_every_definer_function_has_fixed_search_path(self):
        definitions = re.split(r"create or replace function public\\.", self.sql, flags=re.I)[1:]
        self.assertEqual(len(definitions), 9)
        for definition in definitions:
            header = definition.split("as $$", 1)[0].lower()
            self.assertIn("security definer", header)
            self.assertIn("set search_path = pg_catalog, public, pg_temp", header)

    def test_every_privileged_function_is_revoked_and_service_role_granted(self):
        names = re.findall(r"create or replace function public\\.([a-z_]+)", self.sql, flags=re.I)
        for name in names:
            self.assertRegex(self.sql, rf"revoke all on function public\\.{name}\\([^;]+ from public, anon, authenticated;")
            self.assertRegex(self.sql, rf"grant execute on function public\\.{name}\\([^;]+ to service_role;")

    def test_skip_locked_queries_put_limit_before_lock_clause(self):
        self.assertNotRegex(self.sql, r"for update skip locked\\s+limit")
        self.assertEqual(len(re.findall(r"limit [^;]+ for update skip locked", self.sql, flags=re.I)), 3)

    def test_completion_requires_owner_matched_persisted_asset(self):
        completion = self.sql.split("create or replace function public.complete_generation_job", 1)[1]
        completion = completion.split("create or replace function public.fail_generation_job", 1)[0]
        self.assertIn("m.id = p_result_asset_id", completion)
        self.assertIn("m.owner_id = g.owner_id", completion)
        self.assertIn("m.storage_path is not null", completion)
        self.assertIn("g.status = 'processing'", completion)

    def test_fenced_worker_writes_and_expired_lease_recovery_exist(self):
        self.assertIn("g.lease_token = p_lease_token", self.sql)
        self.assertIn("lease_expires_at > now()", self.sql)
        self.assertIn("recover_expired_generation_jobs", self.sql)
        self.assertIn("for update skip locked", self.sql.lower())

    def test_outbox_event_types_match_the_base_table_constraint(self):
        allowed = re.search(r"event_type text not null check \\(event_type in \\(([^)]+)\\)\\)", self.base_sql, flags=re.I)
        self.assertIsNotNone(allowed)
        allowed_types = set(re.findall(r"'([a-z_]+)'", allowed.group(1)))
        emitted_types = set(re.findall(r"values \\([^;]*?'(job_[a-z_]+)'", self.sql, flags=re.I))
        self.assertTrue(emitted_types)
        self.assertLessEqual(emitted_types, allowed_types)

    def test_retry_failure_updates_job_and_outbox_in_same_rpc(self):
        failure = self.sql.split("create or replace function public.fail_generation_job", 1)[1]
        failure = failure.split("create or replace function public.request_generation_job_cancel", 1)[0]
        self.assertIn("for update", failure.lower())
        self.assertIn("status = v_status", failure)
        self.assertIn("insert into public.generation_job_outbox", failure)
        self.assertIn("'job_retry_ready'", failure)

    def test_cancellation_is_owner_scoped_and_not_completable_as_success(self):
        cancel = self.sql.split("create or replace function public.request_generation_job_cancel", 1)[1]
        cancel = cancel.split("create or replace function public.recover_expired_generation_jobs", 1)[0]
        self.assertIn("owner_id = p_owner_id", cancel)
        self.assertIn("status = 'cancel_requested'", cancel)
        completion = self.sql.split("create or replace function public.complete_generation_job", 1)[1]
        completion = completion.split("create or replace function public.fail_generation_job", 1)[0]
        self.assertIn("g.status = 'processing'", completion)
        self.assertNotIn("g.status = 'cancel_requested'", completion)

    def test_behavior_harness_covers_critical_owner_and_lease_cases(self):
        self.assertIn("begin;", self.behavior.lower())
        self.assertIn("rollback;", self.behavior.lower())
        for phrase in (
            "cross-owner result asset was accepted",
            "cross-owner cancellation was not denied",
            "stale completion was accepted",
            "expired lease did not enter retry_wait",
            "duplicate outbox acknowledgement was accepted",
            "exhausted outbox event was not dead-lettered",
        ):
            self.assertIn(phrase, self.behavior)

    def test_read_only_preflight_mentions_all_rpc_functions(self):
        names = re.findall(r"create or replace function public\\.([a-z_]+)", self.sql, flags=re.I)
        for name in names:
            self.assertIn(name, self.preflight)


if __name__ == "__main__":
    unittest.main()
