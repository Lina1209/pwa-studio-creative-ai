"""Pure durable-outbox event lifecycle for future media workers.

No database, scheduler, queue broker, or Storage calls are performed here.
Persist every transition atomically and fence claims in the database.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID


class OutboxStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class MediaOutboxEvent:
    id: str
    owner_id: str
    asset_id: str
    event_type: str
    idempotency_key: str
    status: OutboxStatus = OutboxStatus.PENDING
    available_at: datetime | None = None
    claim_token: str | None = None
    claim_expires_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 8

    def __post_init__(self):
        for field_name in ("id", "owner_id", "asset_id"):
            _uuid(getattr(self, field_name), field_name)
        if self.event_type not in {"media_cleanup_requested", "media_upload_verify_requested", "media_reference_replacement_cleanup_requested"}:
            raise ValueError("Unsupported media outbox event type.")
        if not isinstance(self.idempotency_key, str) or not 8 <= len(self.idempotency_key) <= 160:
            raise ValueError("idempotency_key must contain between 8 and 160 characters.")
        if any(ord(char) < 33 or ord(char) > 126 for char in self.idempotency_key):
            raise ValueError("idempotency_key must be printable ASCII without spaces.")
        if not 1 <= self.max_attempts <= 20 or not 0 <= self.attempts <= self.max_attempts:
            raise ValueError("Outbox attempt counters are outside the allowed range.")
        for value in (self.available_at, self.claim_expires_at):
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
                raise ValueError("Outbox timestamps must be timezone-aware.")
        if self.status is OutboxStatus.CLAIMED:
            if not self.claim_token or not self.claim_expires_at:
                raise ValueError("Claimed events require a token and expiry.")
            _uuid(self.claim_token, "claim token")
        elif self.claim_token is not None or self.claim_expires_at is not None:
            raise ValueError("Only claimed events may retain a claim token or expiry.")


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"A valid {label} UUID is required.") from exc


def claim_media_event(
    event: MediaOutboxEvent, *, now: datetime, claim_token: str, lease_seconds: int = 90
) -> MediaOutboxEvent:
    _now(now)
    token = _uuid(claim_token, "claim token")
    if not 10 <= lease_seconds <= 900:
        raise ValueError("lease_seconds must be between 10 and 900.")
    if event.status is not OutboxStatus.PENDING:
        raise ValueError("Only pending outbox events can be claimed.")
    if event.available_at and event.available_at > now:
        raise ValueError("Outbox event is not available yet.")
    if event.attempts >= event.max_attempts:
        return replace(event, status=OutboxStatus.DEAD_LETTER)
    return replace(
        event, status=OutboxStatus.CLAIMED, claim_token=token,
        claim_expires_at=now + timedelta(seconds=lease_seconds),
        attempts=event.attempts + 1,
    )


def acknowledge_media_event(
    event: MediaOutboxEvent, *, claim_token: str, now: datetime
) -> MediaOutboxEvent:
    _now(now)
    token = _uuid(claim_token, "claim token")
    if event.status is OutboxStatus.DELIVERED:
        return event
    if event.status is not OutboxStatus.CLAIMED or event.claim_token != token:
        raise ValueError("Outbox claim is stale or not owned by this worker.")
    if event.claim_expires_at is None or event.claim_expires_at <= now:
        raise ValueError("Outbox claim has expired.")
    return replace(
        event, status=OutboxStatus.DELIVERED,
        claim_token=None, claim_expires_at=None,
    )


def retry_media_event(
    event: MediaOutboxEvent, *, claim_token: str, now: datetime, retry_delay_seconds: int = 30
) -> MediaOutboxEvent:
    _now(now)
    token = _uuid(claim_token, "claim token")
    if event.status is not OutboxStatus.CLAIMED or event.claim_token != token:
        raise ValueError("Outbox claim is stale or not owned by this worker.")
    if event.claim_expires_at is None or event.claim_expires_at <= now:
        raise ValueError("Outbox claim has expired.")
    if not 1 <= retry_delay_seconds <= 86400:
        raise ValueError("retry_delay_seconds must be between 1 and 86400.")
    status = OutboxStatus.DEAD_LETTER if event.attempts >= event.max_attempts else OutboxStatus.PENDING
    return replace(
        event, status=status, claim_token=None, claim_expires_at=None,
        available_at=now + timedelta(seconds=retry_delay_seconds),
    )


def recover_expired_media_claim(event: MediaOutboxEvent, *, now: datetime) -> MediaOutboxEvent:
    _now(now)
    if event.status is not OutboxStatus.CLAIMED or event.claim_expires_at is None:
        raise ValueError("Only claimed events can have an expired lease.")
    if event.claim_expires_at > now:
        raise ValueError("Outbox claim has not expired.")
    status = OutboxStatus.DEAD_LETTER if event.attempts >= event.max_attempts else OutboxStatus.PENDING
    return replace(
        event, status=status, claim_token=None, claim_expires_at=None, available_at=now
    )


def _now(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime.")
