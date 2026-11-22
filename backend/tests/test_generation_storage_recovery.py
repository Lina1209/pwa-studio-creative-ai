from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.services.generation_storage_recovery import (
    GenerationStorageRecoveryError,
    plan_generation_storage_recovery,
)
from app.services.supabase_generation_worker_repository import GenerationJobInventoryRow
from app.services.supabase_private_image_storage import ListedGeneratedObject


OWNER = UUID("11111111-1111-4111-8111-111111111111")
JOB_OK = UUID("22222222-2222-4222-8222-222222222222")
JOB_FAILED = UUID("33333333-3333-4333-8333-333333333333")
JOB_RUNNING = UUID("44444444-4444-4444-8444-444444444444")
JOB_UNKNOWN = UUID("55555555-5555-4555-8555-555555555555")
NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=10)).isoformat()
RECENT = (NOW - timedelta(hours=2)).isoformat()


def obj(job_id, created=OLD, ext="png"):
    return ListedGeneratedObject(
        object_path=f"{OWNER}/generated/{job_id}.{ext}",
        size_bytes=1234,
        content_type="image/png",
        created_at=created,
    )


def job(job_id, status, result_path=None, updated=OLD):
    return GenerationJobInventoryRow(job_id, status, result_path, updated)


def test_successful_result_is_preserved_only_when_exact_path_matches():
    path = f"{OWNER}/generated/{JOB_OK}.png"
    report = plan_generation_storage_recovery(
        owner_id=OWNER,
        objects=[obj(JOB_OK)],
        jobs=[job(JOB_OK, "succeeded", path)],
        now=NOW,
    )
    assert report.referenced_objects == (path,)
    assert report.orphan_candidates == ()


def test_old_unreferenced_and_terminal_objects_are_candidates_not_deleted():
    missing = obj(JOB_UNKNOWN).object_path
    failed = obj(JOB_FAILED).object_path
    report = plan_generation_storage_recovery(
        owner_id=OWNER,
        objects=[obj(JOB_UNKNOWN), obj(JOB_FAILED)],
        jobs=[job(JOB_FAILED, "failed")],
        now=NOW,
    )
    assert report.orphan_candidates == tuple(sorted([missing, failed]))
    assert report.scanned_objects == 2


def test_live_and_recent_objects_are_preserved_as_pending():
    running_path = obj(JOB_RUNNING).object_path
    recent_path = obj(JOB_UNKNOWN, RECENT).object_path
    report = plan_generation_storage_recovery(
        owner_id=OWNER,
        objects=[obj(JOB_RUNNING), obj(JOB_UNKNOWN, RECENT)],
        jobs=[job(JOB_RUNNING, "running")],
        now=NOW,
    )
    assert report.pending_objects == tuple(sorted([running_path, recent_path]))
    assert report.orphan_candidates == ()


def test_succeeded_job_with_mismatched_path_is_warning_never_candidate():
    report = plan_generation_storage_recovery(
        owner_id=OWNER,
        objects=[obj(JOB_OK)],
        jobs=[job(JOB_OK, "succeeded", f"{OWNER}/generated/different.png")],
        now=NOW,
    )
    assert report.integrity_warnings == (obj(JOB_OK).object_path,)
    assert report.orphan_candidates == ()


def test_unknown_state_or_invalid_timestamp_is_preserved_as_warning():
    report = plan_generation_storage_recovery(
        owner_id=OWNER,
        objects=[
            obj(JOB_OK),
            ListedGeneratedObject(
                f"{OWNER}/generated/not-a-job.png", 100, "image/png", "invalid"
            ),
        ],
        jobs=[job(JOB_OK, "new_future_state")],
        now=NOW,
    )
    assert len(report.integrity_warnings) == 2
    assert report.orphan_candidates == ()


def test_foreign_path_and_duplicate_inventory_are_rejected_or_warned_safely():
    foreign = ListedGeneratedObject(
        f"{UUID(int=9)}/generated/{JOB_UNKNOWN}.png", 100, "image/png", OLD
    )
    report = plan_generation_storage_recovery(
        owner_id=OWNER, objects=[foreign], jobs=[], now=NOW
    )
    assert report.integrity_warnings == (foreign.object_path,)
    with pytest.raises(GenerationStorageRecoveryError):
        plan_generation_storage_recovery(
            owner_id=OWNER, objects=[obj(JOB_UNKNOWN), obj(JOB_UNKNOWN)], jobs=[], now=NOW
        )


def test_duplicate_job_rows_and_invalid_grace_period_fail_closed():
    with pytest.raises(GenerationStorageRecoveryError):
        plan_generation_storage_recovery(
            owner_id=OWNER,
            objects=[],
            jobs=[job(JOB_OK, "failed"), job(JOB_OK, "failed")],
            now=NOW,
        )
    with pytest.raises(ValueError):
        plan_generation_storage_recovery(
            owner_id=OWNER, objects=[], jobs=[], now=NOW, grace_period=timedelta(minutes=5)
        )
