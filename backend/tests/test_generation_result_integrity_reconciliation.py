from uuid import UUID

import pytest

from app.services.generation_result_storage import GenerationResultStorageError
from app.services.generation_storage_recovery import verify_owner_succeeded_results
from app.services.supabase_generation_worker_repository import GenerationJobInventoryRow
from app.services.supabase_private_image_storage import SupabaseStorageAdapterError


OWNER = UUID("11111111-1111-4111-8111-111111111111")
GOOD = UUID("22222222-2222-4222-8222-222222222222")
MISSING_PATH = UUID("33333333-3333-4333-8333-333333333333")
CORRUPT = UUID("44444444-4444-4444-8444-444444444444")
TEMPORARY = UUID("55555555-5555-4555-8555-555555555555")


class FakeRepository:
    def __init__(self, rows):
        self.rows = rows

    async def list_owner_job_inventory(self, owner_id):
        assert owner_id == OWNER
        return self.rows


class FakeStorage:
    async def verify_existing_image(self, *, owner_id, job_id, object_path):
        assert owner_id == OWNER
        if job_id == CORRUPT:
            raise GenerationResultStorageError("stored_object_content_mismatch")
        if job_id == TEMPORARY:
            raise SupabaseStorageAdapterError("storage_request_timeout", retryable=True)
        return object()


def row(job_id, status="succeeded", path=None):
    return GenerationJobInventoryRow(
        job_id=job_id,
        status=status,
        result_storage_path=path,
        updated_at="2026-11-01T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_result_integrity_scan_separates_verified_corrupt_and_deferred():
    rows = [
        row(GOOD, path=f"{OWNER}/generated/{GOOD}.png"),
        row(MISSING_PATH, path=None),
        row(CORRUPT, path=f"{OWNER}/generated/{CORRUPT}.png"),
        row(TEMPORARY, path=f"{OWNER}/generated/{TEMPORARY}.png"),
        row(UUID("66666666-6666-4666-8666-666666666666"), "running"),
    ]
    report = await verify_owner_succeeded_results(
        owner_id=OWNER,
        storage=FakeStorage(),
        repository=FakeRepository(rows),
    )

    assert report.checked_jobs == 4
    assert report.verified_results == (f"{OWNER}/generated/{GOOD}.png",)
    assert report.integrity_failures == (
        (str(MISSING_PATH), "succeeded_job_missing_result_path"),
        (str(CORRUPT), "stored_object_content_mismatch"),
    )
    assert report.deferred_checks == ((str(TEMPORARY), "storage_request_timeout"),)


@pytest.mark.asyncio
async def test_unexpected_programming_errors_are_not_silently_swallowed():
    class BrokenStorage:
        async def verify_existing_image(self, **kwargs):
            raise RuntimeError("unexpected bug")

    with pytest.raises(RuntimeError):
        await verify_owner_succeeded_results(
            owner_id=OWNER,
            storage=BrokenStorage(),
            repository=FakeRepository([
                row(GOOD, path=f"{OWNER}/generated/{GOOD}.png")
            ]),
        )
