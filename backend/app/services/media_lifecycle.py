"""Provider-neutral media lifecycle state machine.

Pure domain logic only: no database writes, Storage calls, queues, or API routes.
A future repository must persist transitions transactionally and use row locking
or compare-and-swap so concurrent requests cannot skip states.
"""
from dataclasses import dataclass
from enum import Enum


class MediaStatus(str, Enum):
    PENDING_UPLOAD = "pending_upload"
    OBJECT_UPLOADED = "object_uploaded"
    READY = "ready"
    UPLOAD_FAILED = "upload_failed"
    CLEANUP_PENDING = "cleanup_pending"
    DELETED = "deleted"


_TRANSITIONS = {
    MediaStatus.PENDING_UPLOAD: frozenset({
        MediaStatus.OBJECT_UPLOADED,
        MediaStatus.UPLOAD_FAILED,
        MediaStatus.CLEANUP_PENDING,
    }),
    MediaStatus.OBJECT_UPLOADED: frozenset({
        MediaStatus.READY,
        MediaStatus.CLEANUP_PENDING,
        MediaStatus.UPLOAD_FAILED,
    }),
    MediaStatus.READY: frozenset({MediaStatus.CLEANUP_PENDING}),
    MediaStatus.UPLOAD_FAILED: frozenset({
        MediaStatus.CLEANUP_PENDING,
        MediaStatus.DELETED,
    }),
    MediaStatus.CLEANUP_PENDING: frozenset({MediaStatus.DELETED}),
    MediaStatus.DELETED: frozenset(),
}


@dataclass(frozen=True)
class MediaLifecycle:
    status: MediaStatus

    @property
    def is_readable(self) -> bool:
        """Only fully committed assets may be listed, read, or signed."""
        return self.status is MediaStatus.READY

    @property
    def needs_cleanup(self) -> bool:
        return self.status is MediaStatus.CLEANUP_PENDING


def transition_media_status(current: MediaStatus | str, target: MediaStatus | str) -> MediaStatus:
    """Validate one lifecycle transition; repeated identical requests are idempotent."""
    try:
        source = MediaStatus(current)
        destination = MediaStatus(target)
    except ValueError as exc:
        raise ValueError("Unknown media lifecycle status.") from exc

    if source is destination:
        return source
    if destination not in _TRANSITIONS[source]:
        raise ValueError(f"Media transition {source.value} -> {destination.value} is not allowed.")
    return destination
