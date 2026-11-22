import asyncio
from decimal import Decimal
from uuid import UUID

import pytest
from types import SimpleNamespace

from app.services.generation_result_storage import (
    GenerationStorageAdapterError,
    StoredObjectMetadata,
    calculate_sha256,
)
from app.services.worker_repository_errors import WorkerRepositoryError
from app.services.generation_worker import (
    ClaimedImageJob,
    GenerationWorker,
    UploadedImageObject,
)
from app.services.image_generation import (
    ImageGenerationError,
    ImageGenerationResult,
    ImageProviderRegistry,
    ProviderUsage,
)


OWNER = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
IMAGE = b"\x89PNG\r\n\x1a\nworker-test-image"
DIGEST = calculate_sha256(IMAGE)


class FakeRepository:
    def __init__(
        self, *, heartbeat=True, complete=True, journal_created=True,
        journal_unknown=True, journal_failed=True, journal_state=None,
        completion_replayed=False,
    ):
        self.heartbeat_result = heartbeat
        self.complete_result = complete
        self.completion_replayed = completion_replayed
        self.journal_created = journal_created
        self.journal_state = journal_state or ("submitting" if journal_created else "unknown")
        self.journal_unknown_result = journal_unknown
        self.journal_failed_result = journal_failed
        self.calls = []

    async def heartbeat(self, *args):
        self.calls.append(("heartbeat", args))
        return self.heartbeat_result

    async def begin_provider_operation(self, *args):
        self.calls.append(("journal_begin", args))
        return SimpleNamespace(created=self.journal_created, state=self.journal_state)

    async def mark_provider_operation_accepted(self, *args):
        self.calls.append(("journal_accepted", args))
        return True

    async def mark_provider_operation_unknown(self, *args):
        self.calls.append(("journal_unknown", args))
        return self.journal_unknown_result

    async def mark_provider_operation_failed(self, *args):
        self.calls.append(("journal_failed", args))
        return self.journal_failed_result

    async def mark_provider_operation_result_received(self, *args):
        self.calls.append(("journal_result", args))
        return True

    async def retry(self, *args):
        self.calls.append(("retry", args))
        return True

    async def fail(self, *args):
        self.calls.append(("fail", args))
        return True

    async def complete_credited(self, *args):
        self.calls.append(("complete", args))
        return SimpleNamespace(
            completed=self.complete_result,
            replayed=self.completion_replayed,
            available_credits=90 if self.complete_result else None,
            reserved_credits=10 if self.complete_result else None,
        )

    async def record_provider_cost(self, **kwargs):
        self.calls.append(("provider_cost", kwargs))
        return SimpleNamespace(
            event_id=1, created=True,
            cumulative_known_cost_usd=kwargs["cost_usd"] or Decimal("0"),
            budget_limit_usd=None, budget_exceeded=None,
        )



@pytest.mark.asyncio
async def test_worker_retries_ambiguous_completion_response_and_accepts_database_replay():
    class LostFirstCompletionResponseRepository(FakeRepository):
        def __init__(self):
            super().__init__(completion_replayed=True)
            self.completion_attempts = 0

        async def complete_credited(self, *args):
            self.completion_attempts += 1
            if self.completion_attempts == 1:
                # Simulate Postgres committing capture + succeeded, while the
                # HTTP response is lost before the worker receives it.
                raise WorkerRepositoryError("database_connection_error", retryable=True)
            return await super().complete_credited(*args)

    repo = LostFirstCompletionResponseRepository()
    result = await make_worker(repo).process(make_job())

    assert result.outcome == "succeeded"
    assert repo.completion_attempts == 2
    assert len([call for call in repo.calls if call[0] == "complete"]) == 1
    assert not any(call[0] == "retry" for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_treats_committed_credited_completion_replay_as_success():
    repo = FakeRepository(completion_replayed=True)
    result = await make_worker(repo).process(make_job())

    assert result.outcome == "succeeded"
    completion = next(call for call in repo.calls if call[0] == "complete")
    assert completion[1][0] == JOB_ID
    assert completion[1][2] == f"{OWNER}/generated/{JOB_ID}.png"


class FakeProvider:
    name = "fake"
    supports_idempotency = True

    def __init__(self, *, error=None):
        self.error = error
        self.idempotency_keys = []

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
    completion = repo.calls[-1][1]
    assert completion[2] == f"{OWNER}/generated/{JOB_ID}.png"
    assert completion[3] == calculate_sha256(IMAGE)


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
    assert next(call for call in repo.calls if call[0] == "retry")[0] == "retry"
    assert next(call for call in repo.calls if call[0] == "retry")[1][-1] == 30


@pytest.mark.asyncio
async def test_worker_rejects_result_from_wrong_model():
    class WrongModel(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            self.idempotency_keys = [idempotency_key]
            return ImageGenerationResult(IMAGE, "image/png", "fake", "other-model")

    repo = FakeRepository()
    result = await make_worker(repo, WrongModel()).process(make_job())
    assert result.outcome == "failed"
    assert next(call for call in repo.calls if call[0] == "fail")[0] == "fail"


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
    assert next(call for call in repo.calls if call[0] == "fail")[0] == "fail"
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
    assert next(call for call in repo.calls if call[0] == "fail")[0] == "fail"
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
async def test_recovered_result_preserves_lookup_provider_request_id_in_journal():
    from app.services.image_generation import ImageGenerationLookup

    class RecoverableProvider(FakeProvider):
        supports_lookup = True

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            return ImageGenerationLookup(
                "succeeded",
                result=ImageGenerationResult(IMAGE, "image/png", "fake", "fake-v1"),
                provider_request_id="provider-request-123",
            )

    repo = FakeRepository(journal_created=False)
    result = await make_worker(repo, RecoverableProvider()).process(make_job())

    assert result.outcome == "succeeded"
    accepted = next(call for call in repo.calls if call[0] == "journal_accepted")
    assert accepted[1][-1] == "provider-request-123"


@pytest.mark.asyncio
async def test_result_received_recovery_does_not_downgrade_journal_state():
    from app.services.image_generation import ImageGenerationLookup

    class RecoverableProvider(FakeProvider):
        supports_lookup = True

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            return ImageGenerationLookup(
                "succeeded",
                result=ImageGenerationResult(
                    IMAGE, "image/png", "fake", "fake-v1",
                    provider_request_id="provider-request-456",
                ),
                provider_request_id="provider-request-456",
            )

    repo = FakeRepository(journal_created=False, journal_state="result_received")
    result = await make_worker(repo, RecoverableProvider()).process(make_job())

    assert result.outcome == "succeeded"
    assert not any(call[0] == "journal_accepted" for call in repo.calls)
    assert any(call[0] == "journal_result" for call in repo.calls)
    assert any(call[0] == "complete" for call in repo.calls)


@pytest.mark.asyncio
async def test_result_received_recovery_never_resubmits_if_provider_reports_not_found():
    from app.services.image_generation import ImageGenerationLookup

    class ExpiredLookupProvider(FakeProvider):
        supports_lookup = True

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            return ImageGenerationLookup("not_found")

        async def generate(self, request, *, idempotency_key):
            raise AssertionError("A result_received operation must never be resubmitted")

    repo = FakeRepository(journal_created=False, journal_state="result_received")
    result = await make_worker(repo, ExpiredLookupProvider()).process(make_job())

    assert result.outcome == "retry_scheduled"
    assert result.error_code == "provider_result_recovery_pending"
    assert not any(call[0] == "journal_unknown" for call in repo.calls)
    assert any(call[0] == "retry" for call in repo.calls)


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



@pytest.mark.asyncio
async def test_worker_stops_if_unknown_journal_transition_is_rejected():
    class LookupUnsupportedProvider(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            raise AssertionError("Existing operation must not be resubmitted")

    repo = FakeRepository(journal_created=False, journal_unknown=False)
    result = await make_worker(repo, LookupUnsupportedProvider()).process(make_job())

    assert result.outcome == "lease_lost"
    assert result.error_code == "provider_journal_transition_rejected"
    assert any(call[0] == "journal_unknown" for call in repo.calls)
    assert not any(call[0] == "retry" for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_stops_if_failed_journal_transition_is_rejected():
    from app.services.image_generation import ImageGenerationLookup

    class FailedProvider(FakeProvider):
        supports_lookup = True

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            return ImageGenerationLookup("failed", error_code="provider_rejected")

    repo = FakeRepository(journal_created=False, journal_failed=False)
    result = await make_worker(repo, FailedProvider()).process(make_job())

    assert result.outcome == "lease_lost"
    assert result.error_code == "provider_journal_transition_rejected"
    assert any(call[0] == "journal_failed" for call in repo.calls)
    assert not any(call[0] == "fail" for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_stops_if_ambiguous_unknown_transition_is_rejected():
    repo = FakeRepository(journal_unknown=False)
    provider = FakeProvider(error=ImageGenerationError(
        "provider_response_lost", retryable=True, ambiguous=True
    ))
    result = await make_worker(repo, provider).process(make_job())

    assert result.outcome == "lease_lost"
    assert result.error_code == "provider_journal_transition_rejected"
    assert not any(call[0] == "retry" for call in repo.calls)


@pytest.mark.asyncio
async def test_ambiguous_provider_submission_is_journaled_before_retry():
    repo = FakeRepository()
    provider = FakeProvider(error=ImageGenerationError(
        "provider_response_lost", retryable=True, ambiguous=True
    ))
    result = await make_worker(repo, provider).process(make_job())

    assert result.outcome == "retry_scheduled"
    assert any(call[0] == "journal_unknown" for call in repo.calls)
    assert repo.calls[-1][0] == "retry"



@pytest.mark.asyncio
async def test_ambiguous_provider_acceptance_recovers_with_same_idempotency_key_and_cost():
    from app.services.image_generation import ImageGenerationLookup

    class EventuallyConsistentProvider(FakeProvider):
        supports_lookup = True

        def __init__(self):
            super().__init__()
            self.lookup_keys = []
            self.result = ImageGenerationResult(
                IMAGE, "image/png", "fake", "fake-v1",
                provider_request_id="provider-request-after-ambiguous-acceptance",
                usage=ProviderUsage(
                    cost_usd=Decimal("0.0125"),
                    cost_source="reported",
                    provider_usage_id="usage-after-ambiguous-acceptance",
                ),
            )

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            self.lookup_keys.append(idempotency_key)
            # Simulate a provider lookup index that has not caught up yet.
            return ImageGenerationLookup("not_found")

        async def generate(self, request, *, idempotency_key):
            # A real adapter must guarantee this same key is deduplicated by
            # the provider; the worker must never create a fresh operation key.
            self.idempotency_keys.append(idempotency_key)
            return self.result

    provider = EventuallyConsistentProvider()
    repo = FakeRepository(journal_created=False, journal_state="unknown")

    result = await make_worker(repo, provider).process(make_job(attempt_count=2))

    assert result.outcome == "succeeded"
    assert provider.lookup_keys == [str(JOB_ID)]
    assert provider.idempotency_keys == [str(JOB_ID)]
    accepted = next(call for call in repo.calls if call[0] == "journal_accepted")
    assert accepted[1][-1] == "provider-request-after-ambiguous-acceptance"
    assert any(call[0] == "journal_result" for call in repo.calls)
    cost = next(call[1] for call in repo.calls if call[0] == "provider_cost")
    assert cost["provider_usage_id"] == "usage-after-ambiguous-acceptance"
    assert cost["operation_key"].startswith(f"provider-usage:{JOB_ID}:")
    assert cost["cost_usd"] == Decimal("0.0125")
    assert sum(call[0] == "complete" for call in repo.calls) == 1


@pytest.mark.asyncio
async def test_transient_storage_failure_schedules_retry_after_provider_result_is_journaled():
    class TemporarilyUnavailableStorage:
        async def upload_image(self, **kwargs):
            raise GenerationStorageAdapterError("storage_request_timeout", retryable=True)

    repo = FakeRepository()
    result = await make_worker(repo, storage=TemporarilyUnavailableStorage()).process(make_job())

    assert result.outcome == "retry_scheduled"
    assert result.error_code == "storage_request_timeout"
    names = [call[0] for call in repo.calls]
    assert names.index("journal_result") < names.index("retry")
    assert not any(name == "complete" for name in names)


@pytest.mark.asyncio
async def test_permanent_storage_failure_uses_terminal_failure():
    class MisconfiguredStorage:
        async def upload_image(self, **kwargs):
            raise GenerationStorageAdapterError("storage_not_configured", retryable=False)

    repo = FakeRepository()
    result = await make_worker(repo, storage=MisconfiguredStorage()).process(make_job())

    assert result.outcome == "failed"
    assert result.error_code == "storage_not_configured"
    assert repo.calls[-1][0] == "fail"
    assert not any(call[0] == "complete" for call in repo.calls)



@pytest.mark.asyncio
async def test_reclaimed_provider_failed_journal_fails_job_without_lookup_or_resubmit():
    class ProviderMustNotBeContacted(FakeProvider):
        supports_lookup = True

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            raise AssertionError("A provider_failed journal is already terminal")

        async def generate(self, request, *, idempotency_key):
            raise AssertionError("A provider_failed journal must never resubmit")

    repo = FakeRepository(journal_created=False, journal_state="provider_failed")
    result = await make_worker(repo, ProviderMustNotBeContacted()).process(make_job())

    assert result.outcome == "failed"
    assert result.error_code == "provider_operation_failed"
    assert any(call[0] == "fail" for call in repo.calls)
    assert not any(call[0] in {"journal_unknown", "journal_accepted", "journal_result"} for call in repo.calls)



@pytest.mark.asyncio
async def test_lease_loss_during_upload_recovers_same_provider_result_and_storage_object():
    from app.services.image_generation import ImageGenerationLookup

    class RecoverableProvider(FakeProvider):
        supports_lookup = True

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            assert idempotency_key == str(JOB_ID)
            return ImageGenerationLookup(
                "succeeded",
                result=ImageGenerationResult(
                    image_bytes=IMAGE,
                    mime_type="image/png",
                    provider="fake",
                    model="fake-v1",
                ),
            )

    class PersistThenPauseStorage(FakeStorage):
        def __init__(self):
            self.persisted = False
            self.calls = 0
            self.paths = []
            self.payloads = []

        async def upload_image(self, *, owner_id, job_id, image_bytes, mime_type):
            self.calls += 1
            self.persisted = True  # Simulate Storage accepting bytes before response loss.
            self.paths.append(f"{owner_id}/generated/{job_id}.png")
            self.payloads.append(image_bytes)
            if self.calls == 1:
                await asyncio.sleep(0.2)  # Worker cancellation after heartbeat reports lost lease.
            return await super().upload_image(
                owner_id=owner_id, job_id=job_id, image_bytes=image_bytes, mime_type=mime_type
            )

    storage = PersistThenPauseStorage()
    first_repo = FakeRepository(heartbeat=False)
    first = await make_worker(first_repo, storage=storage).process(make_job())

    assert first.outcome == "lease_lost"
    assert storage.persisted is True
    assert not any(call[0] == "complete" for call in first_repo.calls)
    assert not any(call[0] in {"retry", "fail"} for call in first_repo.calls)

    recovered_repo = FakeRepository(
        journal_created=False, journal_state="result_received"
    )
    recovery_provider = RecoverableProvider()
    second = await make_worker(
        recovered_repo, recovery_provider, storage
    ).process(make_job(attempt_count=2))

    assert second.outcome == "succeeded"
    assert storage.calls == 2
    assert storage.paths == [f"{OWNER}/generated/{JOB_ID}.png"] * 2
    assert storage.payloads == [IMAGE, IMAGE]
    assert recovery_provider.idempotency_keys == []  # Lookup reused the result; no generation call.
    assert any(call[0] == "complete" for call in recovered_repo.calls)


@pytest.mark.asyncio
async def test_lease_loss_during_journal_begin_prevents_provider_submission():
    class DelayedJournalRepository(FakeRepository):
        async def begin_provider_operation(self, *args):
            await asyncio.sleep(0.04)
            return await super().begin_provider_operation(*args)

    repo = DelayedJournalRepository(heartbeat=False)
    provider = FakeProvider()
    result = await make_worker(repo, provider).process(make_job())

    assert result.outcome == "lease_lost"
    assert provider.idempotency_keys == []
    assert not any(call[0] in {"journal_result", "complete", "retry", "fail"} for call in repo.calls)


@pytest.mark.asyncio
async def test_lease_loss_during_provider_acceptance_prevents_storage_upload():
    class AcceptedResultProvider(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            self.idempotency_keys = [idempotency_key]
            return ImageGenerationResult(
                image_bytes=IMAGE,
                mime_type="image/png",
                provider="fake",
                model="fake-v1",
                provider_request_id="provider-request-1",
            )

    class DelayedAcceptanceRepository(FakeRepository):
        async def mark_provider_operation_accepted(self, *args):
            await asyncio.sleep(0.04)
            return await super().mark_provider_operation_accepted(*args)

    class CountingStorage(FakeStorage):
        def __init__(self):
            self.calls = 0

        async def upload_image(self, **kwargs):
            self.calls += 1
            return await super().upload_image(**kwargs)

    repo = DelayedAcceptanceRepository(heartbeat=False)
    provider = AcceptedResultProvider()
    storage = CountingStorage()
    result = await make_worker(repo, provider, storage).process(make_job())

    assert result.outcome == "lease_lost"
    assert storage.calls == 0
    assert not any(call[0] in {"journal_result", "complete", "retry", "fail"} for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_restart_recovers_ambiguous_submission_without_duplicate_generation():
    from app.services.image_generation import ImageGenerationLookup

    class RestartRecoverableProvider(FakeProvider):
        supports_lookup = True

        def __init__(self):
            super().__init__(error=ImageGenerationError(
                "provider_response_lost", retryable=True, ambiguous=True
            ))
            self.lookup_calls = []

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            self.lookup_calls.append(idempotency_key)
            return ImageGenerationLookup(
                "succeeded",
                result=ImageGenerationResult(
                    IMAGE, "image/png", "fake", "fake-v1"
                ),
                provider_request_id="recovered-request-789",
            )

    provider = RestartRecoverableProvider()

    # First worker persists an ambiguous provider outcome and schedules retry.
    first_repository = FakeRepository()
    first_result = await make_worker(first_repository, provider).process(make_job())

    assert first_result.outcome == "retry_scheduled"
    assert first_result.error_code == "provider_response_lost"
    assert any(call[0] == "journal_unknown" for call in first_repository.calls)
    assert first_repository.calls[-1][0] == "retry"

    # A new worker process reclaims the same durable job and journal.
    restarted_repository = FakeRepository(
        journal_created=False, journal_state="unknown"
    )
    second_result = await make_worker(restarted_repository, provider).process(
        make_job(attempt_count=2)
    )

    assert second_result.outcome == "succeeded"
    assert provider.idempotency_keys == [str(JOB_ID)]
    assert provider.lookup_calls == [str(JOB_ID)]
    assert not any(call[0] == "generate" for call in restarted_repository.calls)
    assert any(call[0] == "journal_result" for call in restarted_repository.calls)
    assert any(call[0] == "complete" for call in restarted_repository.calls)


@pytest.mark.asyncio
async def test_worker_retries_transient_database_disconnect_without_new_provider_submission():
    from app.services.worker_repository_errors import WorkerRepositoryError

    class DisconnectedJournalRepository(FakeRepository):
        async def begin_provider_operation(self, *args):
            raise WorkerRepositoryError("database_connection_error", retryable=True)

    provider = FakeProvider()
    repo = DisconnectedJournalRepository()
    result = await make_worker(repo, provider).process(make_job())

    assert result.outcome == "retry_scheduled"
    assert result.error_code == "database_connection_error"
    assert provider.idempotency_keys == []
    assert any(call[0] == "retry" for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_fails_closed_on_permanent_database_credential_rejection():
    from app.services.worker_repository_errors import WorkerRepositoryError

    class RejectedCredentialsRepository(FakeRepository):
        async def begin_provider_operation(self, *args):
            raise WorkerRepositoryError("database_credentials_rejected", retryable=False)

    provider = FakeProvider()
    repo = RejectedCredentialsRepository()
    result = await make_worker(repo, provider).process(make_job())

    assert result.outcome == "failed"
    assert result.error_code == "database_credentials_rejected"
    assert provider.idempotency_keys == []
    assert any(call[0] == "fail" for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_persists_reported_provider_usage_before_upload_and_completion():
    class MeteredProvider(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            return ImageGenerationResult(
                image_bytes=IMAGE,
                mime_type="image/png",
                provider="fake",
                model="fake-v1",
                provider_request_id="provider-request-metered",
                usage=ProviderUsage(
                    cost_usd=Decimal("0.0042"),
                    cost_source="reported",
                    provider_usage_id="usage-metered-001",
                    input_units=120,
                    output_units=80,
                    total_units=200,
                    unit_kind="token",
                    metadata={"billing_reference": "provider-invoice-line-1"},
                ),
            )

    repo = FakeRepository()
    result = await make_worker(repo, MeteredProvider()).process(make_job())

    assert result.outcome == "succeeded"
    cost_call = next(call for call in repo.calls if call[0] == "provider_cost")
    evidence = cost_call[1]
    assert evidence["job_id"] == JOB_ID
    assert evidence["user_id"] == OWNER
    assert evidence["provider"] == "fake"
    assert evidence["model"] == "fake-v1"
    assert evidence["provider_usage_id"] == "usage-metered-001"
    assert evidence["cost_usd"] == Decimal("0.0042")
    assert evidence["cost_source"] == "reported"
    assert evidence["total_units"] == 200
    assert evidence["operation_key"].startswith(f"provider-usage:{JOB_ID}:")
    assert [call[0] for call in repo.calls].index("provider_cost") < [call[0] for call in repo.calls].index("complete")


@pytest.mark.asyncio
async def test_worker_records_explicit_unknown_usage_without_fabricating_zero_cost():
    class UnknownUsageProvider(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            return ImageGenerationResult(
                IMAGE, "image/png", "fake", "fake-v1",
                usage=ProviderUsage(cost_source="unknown", metadata={"reason": "provider_usage_unavailable"}),
            )

    repo = FakeRepository()
    result = await make_worker(repo, UnknownUsageProvider()).process(make_job())

    assert result.outcome == "succeeded"
    evidence = next(call[1] for call in repo.calls if call[0] == "provider_cost")
    assert evidence["cost_source"] == "unknown"
    assert evidence["cost_usd"] is None
    assert evidence["operation_key"].endswith(":result")


@pytest.mark.asyncio
async def test_worker_retries_if_provider_usage_cannot_be_durably_recorded():
    from app.services.worker_repository_errors import WorkerRepositoryError

    class FailingCostRepository(FakeRepository):
        async def record_provider_cost(self, **kwargs):
            self.calls.append(("provider_cost_failed", kwargs))
            raise WorkerRepositoryError("database_connection_error", retryable=True)

    class MeteredProvider(FakeProvider):
        async def generate(self, request, *, idempotency_key):
            return ImageGenerationResult(
                IMAGE, "image/png", "fake", "fake-v1",
                usage=ProviderUsage(cost_usd=Decimal("0.01"), cost_source="reported"),
            )

    repo = FailingCostRepository()
    result = await make_worker(repo, MeteredProvider()).process(make_job())

    assert result.outcome == "retry_scheduled"
    assert result.error_code == "database_connection_error"
    assert any(call[0] == "provider_cost_failed" for call in repo.calls)
    assert not any(call[0] == "complete" for call in repo.calls)


@pytest.mark.asyncio
async def test_worker_does_not_create_provider_cost_event_when_adapter_has_no_usage_contract():
    repo = FakeRepository()
    result = await make_worker(repo).process(make_job())

    assert result.outcome == "succeeded"
    assert not any(call[0] == "provider_cost" for call in repo.calls)



@pytest.mark.asyncio
async def test_worker_restart_replays_same_provider_cost_operation_after_result_checkpoint():
    from app.services.image_generation import ImageGenerationLookup

    class MeteredRecoverableProvider(FakeProvider):
        supports_lookup = True

        def __init__(self):
            super().__init__()
            self.result = ImageGenerationResult(
                IMAGE, "image/png", "fake", "fake-v1",
                provider_request_id="provider-request-stable",
                usage=ProviderUsage(
                    cost_usd=Decimal("0.0075"),
                    cost_source="reported",
                    provider_usage_id="usage-stable-after-restart",
                ),
            )
            self.lookup_keys = []

        async def generate(self, request, *, idempotency_key):
            self.idempotency_keys.append(idempotency_key)
            return self.result

        async def lookup_by_idempotency_key(self, *, idempotency_key):
            self.lookup_keys.append(idempotency_key)
            return ImageGenerationLookup(
                "succeeded", result=self.result,
                provider_request_id="provider-request-stable",
            )

    class FailOnceStorage(FakeStorage):
        def __init__(self):
            self.calls = 0

        async def upload_image(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise GenerationStorageAdapterError(
                    "temporary_storage_timeout", retryable=True
                )
            return await super().upload_image(**kwargs)

    provider = MeteredRecoverableProvider()
    storage = FailOnceStorage()
    first_repository = FakeRepository()
    first = await make_worker(first_repository, provider, storage).process(make_job())

    assert first.outcome == "retry_scheduled"
    first_cost = next(
        call[1] for call in first_repository.calls if call[0] == "provider_cost"
    )

    # A fresh worker process reclaims the durable result_received operation.
    # Provider lookup returns the original result; generation is not submitted again.
    restarted_repository = FakeRepository(
        journal_created=False, journal_state="result_received"
    )
    second = await make_worker(
        restarted_repository, provider, storage
    ).process(make_job(attempt_count=2))

    second_cost = next(
        call[1] for call in restarted_repository.calls if call[0] == "provider_cost"
    )
    assert second.outcome == "succeeded"
    assert first_cost["operation_key"] == second_cost["operation_key"]
    assert first_cost["provider_usage_id"] == second_cost["provider_usage_id"]
    assert first_cost["cost_usd"] == second_cost["cost_usd"] == Decimal("0.0075")
    assert provider.idempotency_keys == [str(JOB_ID)]
    assert provider.lookup_keys == [str(JOB_ID)]
