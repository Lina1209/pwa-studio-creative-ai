import asyncio
from uuid import UUID

import pytest
from types import SimpleNamespace

from app.services.generation_result_storage import StoredObjectMetadata, calculate_sha256
from app.services.generation_worker import (
    ClaimedImageJob,
    GenerationWorker,
    UploadedImageObject,
)
from app.services.image_generation import (
    ImageGenerationError,
    ImageGenerationResult,
    ImageProviderRegistry,
)


OWNER = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
IMAGE = b"\x89PNG\r\n\x1a\nworker-test-image"
DIGEST = calculate_sha256(IMAGE)


class FakeRepository:
    def __init__(self, *, heartbeat=True, complete=True, journal_created=True):
        self.heartbeat_result = heartbeat
        self.complete_result = complete
        self.journal_created = journal_created
        self.calls = []

    async def heartbeat(self, *args):
        self.calls.append(("heartbeat", args))
        return self.heartbeat_result

    async def begin_provider_operation(self, *args):
        self.calls.append(("journal_begin", args))
        return SimpleNamespace(created=self.journal_created, state="submitting" if self.journal_created else "unknown")

    async def mark_provider_operation_accepted(self, *args):
        self.calls.append(("journal_accepted", args))
        return True

    async def mark_provider_operation_unknown(self, *args):
        self.calls.append(("journal_unknown", args))
        return True

    async def mark_provider_operation_failed(self, *args):
        self.calls.append(("journal_failed", args))
        return True

    async def mark_provider_operation_result_received(self, *args):
        self.calls.append(("journal_result", args))
        return True

    async def retry(self, *args):
        self.calls.append(("retry", args))
        return True

    async def fail(self, *args):
        self.calls.append(("fail", args))
        return True

    async def complete(self, *args):
        self.calls.append(("complete", args))
        return self.complete_result


class FakeProvider:
    name = "fake"
    supports_idempotency = True

    def __init__(self, *, error=None):
        self.error = error

    async def generate(self, request, *, idempotency_key):
        self.idempotency_keys = getattr(self, "idempotency_keys", []) + [idempotency_key]
        if self.error:
            raise self.error
        return ImageGenerationResult(
            image_bytes=IMAGE,
            mime_type="image/png",
            provider="fake",
            model="fake-v1",
        )


class FakeStorage:
    async def upload_image(self, *, owner_id, job_id, image_bytes, mime_type):
        assert image_bytes == IMAGE
        assert mime_type == "image/png"
        path = f"{owner_id}/generated/{job_id}.png"
        return UploadedImageObject(
            metadata=StoredObjectMetadata(
                bucket="studio-media",
                object_path=path,
                is_private=True,
                content_type="image/png",
                size_bytes=len(IMAGE),
                sha256_hex=DIGEST,
            ),
            expected_bucket="studio-media",
            expected_object_path=path,
            expected_sha256_hex=DIGEST,
        )


def make_job(**changes):
    values = {
        "job_id": JOB_ID,
        "user_id": OWNER,
        "job_type": "image_generation",
        "provider": "fake",
        "model": "fake-v1",
        "request_snapshot": {"prompt": "a calm forest", "width": 1024, "height": 1024},
        "attempt_count": 1,
        "max_attempts": 3,
    }
    values.update(changes)
    return ClaimedImageJob(**values)


def make_worker(repo=None, provider=None, storage=None):
    registry = ImageProviderRegistry()
    registry.register(provider or FakeProvider())
    return GenerationWorker(
        worker_id="test-worker",
        repository=repo or FakeRepository(),
        providers=registry,
        storage=storage or FakeStorage(),
        heartbeat_interval_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_worker_generates_verifies_upload_then_completes():
    repo = FakeRepository()
    result = await make_worker(repo).process(make_job())
    assert result.outcome == "succeeded"
    assert repo.calls[-1][0] == "complete"


@pytest.mark.asyncio
async def test_non_retryable_provider_error_uses_terminal_failure():
    repo = FakeRepository()
    worker = make_worker(repo, FakeProvider(error=ImageGenerationError("bad_request", retryable=False)))
    result = await worker.process(make_job())
    assert result.outcome == "failed"
    assert repo.calls[-1][0] == "fail"


@pytest.mark.asyncio
async def test_retryable_provider_error_uses_bounded_retry():
    repo = FakeRepository()
    worker = make_worker(repo, FakeProvider(error=ImageGenerationError("rate_limited", retryable=True)))
    result = await worker.process(make_job(attempt_count=2))
    assert result.outcome == "retry_scheduled"
    assert repo.calls[0][0] == "retry"
    assert repo.calls[0][1][-1] == 30


@pytest.mark.asyncio
async def test_worker_rejects_result_from_wrong_model():
    class WrongModel(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            self.idempotency_keys = [idempotency_key]
            return ImageGenerationResult(IMAGE, "image/png", "fake", "other-model")

    repo = FakeRepository()
    result = await make_worker(repo, WrongModel()).process(make_job())
    assert result.outcome == "failed"
    assert repo.calls[0][0] == "fail"


@pytest.mark.asyncio
async def test_worker_does_not_complete_if_upload_metadata_is_public():
    class PublicStorage(FakeStorage):
        async def upload_image(self, *, owner_id, job_id, image_bytes, mime_type):
            uploaded = await super().upload_image(
                owner_id=owner_id, job_id=job_id, image_bytes=image_bytes, mime_type=mime_type
            )
            return UploadedImageObject(
                metadata=StoredObjectMetadata(
                    **{**uploaded.metadata.__dict__, "is_private": False}
                ),
                expected_bucket=uploaded.expected_bucket,
                expected_object_path=uploaded.expected_object_path,
                expected_sha256_hex=uploaded.expected_sha256_hex,
            )

    repo = FakeRepository()
    result = await make_worker(repo, storage=PublicStorage()).process(make_job())
    assert result.outcome == "failed"
    assert repo.calls[0][0] == "fail"
    assert not any(call[0] == "complete" for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_reports_lost_lease_when_completion_is_rejected():
    repo = FakeRepository(complete=False)
    result = await make_worker(repo).process(make_job())
    assert result.outcome == "lease_lost"


@pytest.mark.asyncio
async def test_worker_stops_provider_when_lease_is_lost():
    class SlowProvider(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            await asyncio.sleep(0.2)
            return await super().generate(request, idempotency_key=idempotency_key)

    repo = FakeRepository(heartbeat=False)
    result = await make_worker(repo, SlowProvider()).process(make_job())
    assert result.outcome == "lease_lost"
    assert any(call[0] == "heartbeat" for call in repo.calls)
    assert not any(call[0] in {"complete", "retry", "fail"} for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_rejects_storage_checksum_not_bound_to_generated_bytes():
    class WrongChecksumStorage(FakeStorage):
        async def upload_image(self, *, owner_id, job_id, image_bytes, mime_type):
            uploaded = await super().upload_image(
                owner_id=owner_id, job_id=job_id, image_bytes=image_bytes, mime_type=mime_type
            )
            return UploadedImageObject(
                metadata=uploaded.metadata,
                expected_bucket=uploaded.expected_bucket,
                expected_object_path=uploaded.expected_object_path,
                expected_sha256_hex="0" * 64,
            )

    repo = FakeRepository()
    result = await make_worker(repo, storage=WrongChecksumStorage()).process(make_job())
    assert result.outcome == "failed"
    assert repo.calls[0][0] == "fail"
    assert not any(call[0] == "complete" for call in repo.calls)



@pytest.mark.asyncio
async def test_worker_passes_stable_job_id_as_provider_idempotency_key():
    provider = FakeProvider()
    worker = make_worker(provider=provider)
    first = await worker.process(make_job(attempt_count=1))
    second = await worker.process(make_job(attempt_count=2))
    assert first.outcome == "succeeded"
    assert second.outcome == "succeeded"
    assert provider.idempotency_keys == [str(JOB_ID), str(JOB_ID)]


@pytest.mark.asyncio
async def test_worker_fails_closed_for_provider_without_idempotency_support():
    class UnsafeProvider(FakeProvider):
        supports_idempotency = False

        async def generate(self, request, *, idempotency_key):
            raise AssertionError("Provider must not be called without idempotency support")

    repo = FakeRepository()
    result = await make_worker(repo, UnsafeProvider()).process(make_job())
    assert result.outcome == "failed"
    assert result.error_code == "provider_idempotency_not_supported"
    assert repo.calls[0][0] == "fail"



@pytest.mark.asyncio
async def test_reclaimed_unknown_operation_uses_existing_provider_result_without_resubmitting():
    from app.services.image_generation import ImageGenerationLookup

    class RecoverableProvider(FakeProvider):
        supports_lookup = True

        def __init__(self):
            super().__init__()
            self.lookup_calls = []

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            self.lookup_calls.append(idempotency_key)
            return ImageGenerationLookup(
                "succeeded",
                result=ImageGenerationResult(IMAGE, "image/png", "fake", "fake-v1"),
            )

    provider = RecoverableProvider()
    repo = FakeRepository(journal_created=False)
    result = await make_worker(repo, provider).process(make_job())

    assert result.outcome == "succeeded"
    assert provider.idempotency_keys == []
    assert provider.lookup_calls == [str(JOB_ID)]
    assert repo.calls[-1][0] == "complete"


@pytest.mark.asyncio
async def test_reclaimed_unknown_operation_never_submits_when_lookup_is_pending():
    from app.services.image_generation import ImageGenerationLookup

    class PendingProvider(FakeProvider):
        supports_lookup = True

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            return ImageGenerationLookup("pending")

        async def generate(self, request, *, idempotency_key):
            raise AssertionError("Pending operation must never be resubmitted")

    repo = FakeRepository(journal_created=False)
    result = await make_worker(repo, PendingProvider()).process(make_job())

    assert result.outcome == "retry_scheduled"
    assert result.error_code == "provider_operation_quarantined"
    assert repo.calls[-1][0] == "retry"


@pytest.mark.asyncio
async def test_reclaimed_unknown_operation_without_lookup_is_quarantined():
    class LookupUnsupportedProvider(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            raise AssertionError("Ambiguous operation must not be blindly resubmitted")

    repo = FakeRepository(journal_created=False)
    result = await make_worker(repo, LookupUnsupportedProvider()).process(make_job())

    assert result.outcome == "retry_scheduled"
    assert result.error_code == "provider_operation_quarantined"
    assert repo.calls[-1][0] == "retry"
