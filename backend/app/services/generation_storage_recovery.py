"""Read-only reconciliation planner for generated Storage objects.

This module never deletes objects. It identifies aged candidates only after
comparing a complete owner-scoped Storage inventory with that owner's job
inventory. Any incomplete inventory must fail the scan rather than infer orphans.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.services.supabase_generation_worker_repository import GenerationJobInventoryRow
from app.services.supabase_private_image_storage import ListedGeneratedObject


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
