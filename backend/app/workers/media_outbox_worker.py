"""Long-running, database-backed private media verification worker.

Run with: python -m app.workers.media_outbox_worker
No HTTP listener, broker, or public endpoint is exposed.
"""
import hashlib
import logging
import re
import signal
import time
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.services.media_content import download_private_media_image
from app.services.media_read import MediaReadPlan
from app.services.media_verification_repository import (
    claim_media_upload_verification,
    complete_media_upload_verification,
    retry_media_upload_verification,
)

logger = logging.getLogger("pwa.media_worker")
POLL_INTERVAL_SECONDS = 3
CLAIM_LEASE_SECONDS = 120
MAX_RETRY_DELAY_SECONDS = 3600
_running = True


def _request_shutdown(_signum, _frame):
    global _running
    _running = False


def _validate_claim(event: dict) -> None:
    """Validate every database claim field before using it in a Storage request."""
    if not isinstance(event, dict):
        raise ValueError("Media verification claim must be an object.")
    for field in ("owner_id", "asset_id", "event_id", "claim_token"):
        try:
            if str(UUID(str(event.get(field)))) != event.get(field):
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Media verification claim contains an invalid identifier.") from exc
    if event.get("bucket") != "studio-media":
        raise ValueError("Media verification claim references an unsupported bucket.")
    path = event.get("storage_path")
    if not isinstance(path, str) or path.startswith("/") or "\\" in path:
        raise ValueError("Media verification claim contains an invalid object key.")
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != event["owner_id"] or parts[1] != "characters":
        raise ValueError("Media verification claim object key is outside the character namespace.")
    try:
        UUID(parts[2])
        object_name, extension = parts[3].rsplit(".", 1)
        UUID(object_name)
    except (ValueError, TypeError, IndexError) as exc:
        raise ValueError("Media verification claim contains a malformed object key.") from exc
    mime_to_extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    if event.get("file_type") not in mime_to_extension or extension != mime_to_extension[event["file_type"]]:
        raise ValueError("Media verification claim MIME type and object extension disagree.")
    if not isinstance(event.get("file_name"), str) or not event["file_name"] or len(event["file_name"]) > 255:
        raise ValueError("Media verification claim contains an invalid filename.")
    size = event.get("size_bytes")
    width, height = event.get("width"), event.get("height")
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 8 * 1024 * 1024:
        raise ValueError("Media verification claim contains an invalid byte count.")
    if (not isinstance(width, int) or isinstance(width, bool)
            or not isinstance(height, int) or isinstance(height, bool)
            or not 1 <= width <= 8192 or not 1 <= height <= 8192
            or width * height > 16_000_000):
        raise ValueError("Media verification claim contains invalid image dimensions.")
    if not isinstance(event.get("content_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", event["content_sha256"]):
        raise ValueError("Media verification claim contains an invalid content digest.")
    if type(event.get("attempts")) is not int or not 1 <= event["attempts"] <= 8:
        raise ValueError("Media verification claim contains an invalid attempt counter.")
    if not isinstance(event.get("max_attempts"), int) or event["max_attempts"] != 8:
        raise ValueError("Media verification claim contains an invalid retry limit.")


def verify_claimed_media(settings, event: dict):
    """Download and fully decode the private object, then verify its reservation fingerprint."""
    _validate_claim(event)
    plan = MediaReadPlan(
        owner_id=event["owner_id"],
        asset_id=event["asset_id"],
        bucket=event["bucket"],
        storage_path=event["storage_path"],
    )
    image = download_private_media_image(
        settings,
        plan,
        file_name=event["file_name"],
        expected_mime_type=event["file_type"],
    )
    digest = hashlib.sha256(image.content).hexdigest()
    expected = {
        "size_bytes": int(event["size_bytes"]),
        "content_sha256": event["content_sha256"],
        "file_type": event["file_type"],
        "width": int(event["width"]),
        "height": int(event["height"]),
    }
    actual = {
        "size_bytes": image.size_bytes,
        "content_sha256": digest,
        "file_type": image.mime_type,
        "width": image.width,
        "height": image.height,
    }
    if actual != expected:
        raise ValueError("Stored media does not match its reserved content fingerprint.")
    return image


def process_one(settings) -> bool:
    """Claim and process one event. Returns False when the queue is currently empty."""
    event = claim_media_upload_verification(settings, str(uuid4()), CLAIM_LEASE_SECONDS)
    if event is None:
        return False
    try:
        verified = verify_claimed_media(settings, event)
        complete_media_upload_verification(settings, event, verified)
        logger.info("Verified private media asset %s", event["asset_id"])
    except Exception as exc:
        raw_attempt = event.get("attempts", 1)
        attempt = raw_attempt if isinstance(raw_attempt, int) and not isinstance(raw_attempt, bool) and raw_attempt > 0 else 1
        delay = min(MAX_RETRY_DELAY_SECONDS, 30 * (2 ** max(0, attempt - 1)))
        try:
            outcome = retry_media_upload_verification(settings, event, delay)
            logger.warning(
                "Private media verification deferred for asset %s (attempt %s, outcome %s, error %s)",
                event.get("asset_id", "unknown"), attempt, outcome.get("event_status"), type(exc).__name__,
            )
        except Exception as retry_exc:
            # The lease expires and the database claim RPC recovers it; never clear a
            # claim locally or acknowledge work whose outcome is uncertain.
            logger.error(
                "Could not schedule media verification retry for asset %s (%s)",
                event.get("asset_id", "unknown"), type(retry_exc).__name__,
            )
    return True


def main():
    global _running
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    settings = get_settings()
    logger.info("Private media verification worker started")
    while _running:
        try:
            found = process_one(settings)
        except Exception as exc:
            logger.error("Media verification poll failed (%s)", type(exc).__name__)
            found = False
        if not found and _running:
            time.sleep(POLL_INTERVAL_SECONDS)
    logger.info("Private media verification worker stopped gracefully")


if __name__ == "__main__":
    main()
