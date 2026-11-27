"""Long-running, database-backed private media verification worker.

Run with: python -m app.workers.media_outbox_worker
No HTTP listener, broker, or public endpoint is exposed.
"""
import hashlib
import logging
import signal
import time
from uuid import uuid4

from fastapi import HTTPException

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


def verify_claimed_media(settings, event: dict):
    """Download and fully decode the private object, then verify its reservation fingerprint."""
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
        attempt = int(event.get("attempts", 1))
        delay = min(MAX_RETRY_DELAY_SECONDS, 30 * (2 ** max(0, attempt - 1)))
        try:
            outcome = retry_media_upload_verification(settings, event, delay)
            logger.warning(
                "Private media verification deferred for asset %s (attempt %s, outcome %s, error %s)",
                event["asset_id"], attempt, outcome.get("event_status"), type(exc).__name__,
            )
        except Exception as retry_exc:
            # The lease expires and the database claim RPC recovers it; never clear a
            # claim locally or acknowledge work whose outcome is uncertain.
            logger.error(
                "Could not schedule media verification retry for asset %s (%s)",
                event["asset_id"], type(retry_exc).__name__,
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
