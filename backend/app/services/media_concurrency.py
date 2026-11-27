"""Pure optimistic-concurrency and fencing checks for media mutations.

The database must issue/increment versions and fencing numbers atomically.
This helper only rejects stale work; it is not a substitute for row locks,
conditional UPDATE statements, or a durable idempotency record.
"""
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MediaMutationPermit:
    operation_id: str
    expected_version: int
    next_version: int
    fencing_token: int


def _positive_int(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer.")
    return value


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"A valid {label} UUID is required.") from exc


def authorize_media_mutation(
    *,
    operation_id: str,
    expected_version: int,
    current_version: int,
    supplied_fencing_token: int,
    current_fencing_token: int,
) -> MediaMutationPermit:
    """Reject stale version/fence values before preparing a database mutation."""
    operation = _uuid(operation_id, "operation")
    expected = _positive_int(expected_version, "Expected version")
    current = _positive_int(current_version, "Current version")
    supplied_fence = _positive_int(supplied_fencing_token, "Supplied fencing token")
    current_fence = _positive_int(current_fencing_token, "Current fencing token")

    if expected != current:
        raise ValueError("Media asset changed; reload before retrying.")
    if supplied_fence != current_fence:
        raise ValueError("This media operation is stale and no longer owns the lease.")
    return MediaMutationPermit(
        operation_id=operation,
        expected_version=current,
        next_version=current + 1,
        fencing_token=current_fence,
    )
