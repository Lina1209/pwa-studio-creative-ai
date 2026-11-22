from datetime import datetime, timezone
from uuid import UUID

from app.services.generation_storage_recovery import plan_generation_job_recovery
from app.services.supabase_generation_worker_repository import GenerationJobInventoryRow


OWNER = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)


def make_job(number, status, *, lease=None, attempts=0, maximum=3, available=None):
    return GenerationJobInventoryRow(
        UUID(f"{number:08d}-2222-4222-8222-222222222222"),
        status,
        None,
        "2026-11-20T10:00:00+00:00",
        lease,
        attempts,
        maximum,
        available,
        None,
    )


def test_job_recovery_classifies_live_expired_exhausted_and_retry_jobs():
    jobs = [
        make_job(1, "running", lease="2026-11-22T12:05:00+00:00", attempts=1),
        make_job(2, "running", lease="2026-11-22T11:00:00+00:00", attempts=1),
        make_job(3, "running", lease="2026-11-22T11:00:00+00:00", attempts=3),
        make_job(4, "queued"),
        make_job(5, "retry_wait", available="2026-11-22T11:00:00+00:00"),
        make_job(6, "retry_wait", available="2026-11-22T13:00:00+00:00"),
        make_job(7, "succeeded"),
    ]
    report = plan_generation_job_recovery(owner_id=OWNER, jobs=jobs, now=NOW)

    assert report.scanned_jobs == 7
    assert len(report.active_leases) == 1
    assert len(report.expired_leases_reclaimable) == 1
    assert len(report.expired_leases_exhausted) == 1
    assert len(report.queued_jobs) == 1
    assert len(report.retry_wait_ready) == 1
    assert len(report.retry_wait_delayed) == 1
    assert report.integrity_warnings == ()


def test_job_recovery_warns_on_missing_lease_or_retry_schedule():
    jobs = [
        make_job(8, "running", lease=None),
        make_job(9, "retry_wait", available=None),
        make_job(10, "future_state"),
    ]
    report = plan_generation_job_recovery(owner_id=OWNER, jobs=jobs, now=NOW)
    assert len(report.integrity_warnings) == 3
    assert not report.expired_leases_reclaimable

import pytest
from app.services.generation_storage_recovery import scan_owner_generation_jobs


@pytest.mark.asyncio
async def test_scan_owner_generation_jobs_uses_complete_repository_inventory():
    class Repository:
        async def list_owner_job_inventory(self, owner_id):
            assert owner_id == OWNER
            return [make_job(11, "queued")]

    report = await scan_owner_generation_jobs(
        owner_id=OWNER, repository=Repository(), now=NOW
    )
    assert report.scanned_jobs == 1
    assert len(report.queued_jobs) == 1
