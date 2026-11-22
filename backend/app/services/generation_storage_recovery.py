"""Read-only reconciliation planner for generated Storage objects.

This module never deletes objects. It identifies aged candidates only after
comparing a complete owner-scoped Storage inventory with that owner's job
inventory. Any incomplete inventory must fail the scan rather than infer orphans.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.services.generation_result_storage import GenerationResultStorageError
from app.services.supabase_generation_worker_repository import (
    GenerationJobInventoryRow,
    SupabaseGenerationJobRepository,
)
from app.services.supabase_private_image_storage import (
    ListedGeneratedObject,
    SupabasePrivateImageStorage,
    SupabaseStorageAdapterError,
)


TERMINAL_ORPHAN_STATUSES = frozenset({"failed", "cancelled", "expired"})
LIVE_STATUSES = frozenset({"queued", "running", "retry_wait", "cancel_requested"})


class GenerationStorageRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageRecoveryReport:
    owner_id: UUID
    scanned_objects: int
    referenced_objects: tuple[str, ...]
    pending_objects: tuple[str, ...]
    orphan_candidates: tuple[str, ...]
    integrity_warnings: tuple[str, ...]


def _parse_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _job_id_from_object_path(path: str, owner_id: UUID) -> UUID | None:
    prefix = f"{owner_id}/generated/"
    if not path.startswith(prefix):
        return None
    filename = path[len(prefix):]
    if "/" in filename or "." not in filename:
        return None
    stem, extension = filename.rsplit(".", 1)
    if extension not in {"png", "jpg", "webp"}:
        return None
    try:
        return UUID(stem)
    except ValueError:
        return None


def plan_generation_storage_recovery(
    *,
    owner_id: UUID,
    objects: list[ListedGeneratedObject],
    jobs: list[GenerationJobInventoryRow],
    now: datetime | None = None,
    grace_period: timedelta = timedelta(days=7),
) -> StorageRecoveryReport:
    """Classify stale objects; never perform destructive storage operations."""
    if grace_period < timedelta(hours=1) or grace_period > timedelta(days=365):
        raise ValueError("Recovery grace period must be between 1 hour and 365 days.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Recovery scan time must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    cutoff = current - grace_period

    jobs_by_id: dict[UUID, GenerationJobInventoryRow] = {}
    for job in jobs:
        if job.job_id in jobs_by_id:
            raise GenerationStorageRecoveryError("duplicate_job_inventory_row")
        jobs_by_id[job.job_id] = job

    referenced: list[str] = []
    pending: list[str] = []
    candidates: list[str] = []
    warnings: list[str] = []
    seen_paths: set[str] = set()

    for item in objects:
        path = item.object_path
        if path in seen_paths:
            raise GenerationStorageRecoveryError("duplicate_storage_inventory_path")
        seen_paths.add(path)
        if not path.startswith(f"{owner_id}/generated/") or ".." in path.split("/"):
            warnings.append(path)
            continue

        object_created = _parse_timestamp(item.created_at)
        if object_created is None:
            warnings.append(path)
            continue

        job_id = _job_id_from_object_path(path, owner_id)
        if job_id is None:
            warnings.append(path)
            continue
        job = jobs_by_id.get(job_id)
        if job is None:
            if object_created <= cutoff:
                candidates.append(path)
            else:
                pending.append(path)
            continue

        if job.status == "succeeded":
            if job.result_storage_path == path:
                referenced.append(path)
            else:
                # A successful job's result must never be deleted by cleanup.
                warnings.append(path)
            continue

        if job.status in LIVE_STATUSES:
            pending.append(path)
            continue

        if job.status in TERMINAL_ORPHAN_STATUSES:
            job_updated = _parse_timestamp(job.updated_at)
            if job_updated is None:
                warnings.append(path)
            elif object_created <= cutoff and job_updated <= cutoff:
                candidates.append(path)
            else:
                pending.append(path)
            continue

        # Unknown or newly introduced states are preserved by default.
        warnings.append(path)

    return StorageRecoveryReport(
        owner_id=owner_id,
        scanned_objects=len(objects),
        referenced_objects=tuple(sorted(referenced)),
        pending_objects=tuple(sorted(pending)),
        orphan_candidates=tuple(sorted(candidates)),
        integrity_warnings=tuple(sorted(warnings)),
    )


async def scan_owner_generation_storage(
    *,
    owner_id: UUID,
    storage: SupabasePrivateImageStorage,
    repository: SupabaseGenerationJobRepository,
    now: datetime | None = None,
    grace_period: timedelta = timedelta(days=7),
) -> StorageRecoveryReport:
    """Build a complete, read-only inventory before planning any cleanup."""
    objects = await storage.list_owner_generated_objects(owner_id=owner_id)
    jobs = await repository.list_owner_job_inventory(owner_id)
    return plan_generation_storage_recovery(
        owner_id=owner_id,
        objects=objects,
        jobs=jobs,
        now=now,
        grace_period=grace_period,
    )

@dataclass(frozen=True)
class GenerationResultIntegrityReport:
    owner_id: UUID
    checked_jobs: int
    verified_results: tuple[str, ...]
    integrity_failures: tuple[tuple[str, str], ...]
    deferred_checks: tuple[tuple[str, str], ...]


async def verify_owner_succeeded_results(
    *,
    owner_id: UUID,
    storage: SupabasePrivateImageStorage,
    repository: SupabaseGenerationJobRepository,
) -> GenerationResultIntegrityReport:
    """Re-check every succeeded result for one owner; never changes job state.

    A transport/timeout failure is deferred, not reported as file corruption.
    Definitive metadata or content validation failures are reported separately.
    """
    jobs = await repository.list_owner_job_inventory(owner_id)
    verified: list[str] = []
    failures: list[tuple[str, str]] = []
    deferred: list[tuple[str, str]] = []
    checked = 0

    for job in jobs:
        if job.status != "succeeded":
            continue
        checked += 1
        path = job.result_storage_path
        if not path:
            failures.append((str(job.job_id), "succeeded_job_missing_result_path"))
            continue
        try:
            await storage.verify_existing_image(
                owner_id=owner_id, job_id=job.job_id, object_path=path
            )
            verified.append(path)
        except (GenerationResultStorageError, SupabaseStorageAdapterError) as exc:
            code = exc.error_code
            if getattr(exc, "retryable", False):
                deferred.append((str(job.job_id), code))
            else:
                failures.append((str(job.job_id), code))

    return GenerationResultIntegrityReport(
        owner_id=owner_id,
        checked_jobs=checked,
        verified_results=tuple(sorted(verified)),
        integrity_failures=tuple(sorted(failures)),
        deferred_checks=tuple(sorted(deferred)),
    )

@dataclass(frozen=True)
class GenerationJobRecoveryReport:
    owner_id: UUID
    scanned_jobs: int
    active_leases: tuple[str, ...]
    expired_leases_reclaimable: tuple[str, ...]
    expired_leases_exhausted: tuple[str, ...]
    queued_jobs: tuple[str, ...]
    retry_wait_ready: tuple[str, ...]
    retry_wait_delayed: tuple[str, ...]
    integrity_warnings: tuple[tuple[str, str], ...]


def plan_generation_job_recovery(
    *,
    owner_id: UUID,
    jobs: list[GenerationJobInventoryRow],
    now: datetime | None = None,
) -> GenerationJobRecoveryReport:
    """Classify worker leases and retry eligibility without changing DB state.

    The database claim RPC remains the sole authority that actually reclaims
    expired leases or terminally fails exhausted jobs.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Recovery scan time must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    active: list[str] = []
    reclaimable: list[str] = []
    exhausted: list[str] = []
    queued: list[str] = []
    retry_ready: list[str] = []
    retry_delayed: list[str] = []
    warnings: list[tuple[str, str]] = []
    seen: set[UUID] = set()

    for job in jobs:
        if job.job_id in seen:
            raise GenerationStorageRecoveryError("duplicate_job_inventory_row")
        seen.add(job.job_id)
        job_id = str(job.job_id)
        if job.status == "running":
            lease_end = _parse_timestamp(job.lease_expires_at)
            if lease_end is None:
                warnings.append((job_id, "running_job_missing_valid_lease_expiry"))
            elif lease_end > current:
                active.append(job_id)
            elif job.attempt_count >= job.max_attempts:
                exhausted.append(job_id)
            else:
                reclaimable.append(job_id)
        elif job.status == "queued":
            queued.append(job_id)
        elif job.status == "retry_wait":
            available = _parse_timestamp(job.available_at)
            if available is None:
                warnings.append((job_id, "retry_wait_job_missing_valid_available_at"))
            elif available <= current:
                retry_ready.append(job_id)
            else:
                retry_delayed.append(job_id)
        elif job.status not in {
            "succeeded", "failed", "cancel_requested", "cancelled", "expired"
        }:
            warnings.append((job_id, "unknown_job_status"))

    return GenerationJobRecoveryReport(
        owner_id=owner_id,
        scanned_jobs=len(jobs),
        active_leases=tuple(sorted(active)),
        expired_leases_reclaimable=tuple(sorted(reclaimable)),
        expired_leases_exhausted=tuple(sorted(exhausted)),
        queued_jobs=tuple(sorted(queued)),
        retry_wait_ready=tuple(sorted(retry_ready)),
        retry_wait_delayed=tuple(sorted(retry_delayed)),
        integrity_warnings=tuple(sorted(warnings)),
    )
