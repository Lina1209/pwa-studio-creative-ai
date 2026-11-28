"""Long-running, database-backed private media cleanup worker.

Run with: python -m app.workers.media_cleanup_worker
No HTTP listener or public endpoint is exposed.
"""
import logging
import signal
import time
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.services.media_cleanup import plan_media_cleanup
from app.services.media_cleanup_repository import (
    claim_media_cleanup,
    complete_media_cleanup,
    retry_media_cleanup,
)
from app.services.media_storage_delete import delete_private_media_object

logger = logging.getLogger("pwa.media_cleanup_worker")
POLL_INTERVAL_SECONDS = 3
CLAIM_LEASE_SECONDS = 120
MAX_RETRY_DELAY_SECONDS = 3600
_running = True


def _request_shutdown(_signum, _frame):
    global _running
    _running = False


def _validate_claim(event: dict) -> None:
    """Validate all DB claim fields before any Storage request."""
    if not isinstance(event, dict):
        raise ValueError("Media cleanup claim must be an object.")
    for field in ("owner_id", "asset_id", "character_id", "event_id", "claim_token"):
        try:
            value = str(UUID(str(event.get(field))))
            if value != event.get(field):
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Media cleanup claim contains an invalid identifier.") from exc
    if event.get("bucket") != "studio-media":
        raise ValueError("Media cleanup claim references an unsupported private bucket.")
    path = event.get("storage_path")
    if not isinstance(path, str) or path.startswith("/") or "\\" in path:
        raise ValueError("Media cleanup claim contains an invalid object key.")
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != event["owner_id"] or parts[1] != "characters" or parts[2] != event["character_id"]:
        raise ValueError("Media cleanup claim object key is outside the owner's namespace.")
    try:
        resource_id = str(UUID(parts[2]))
        object_name, extension = parts[3].rsplit(".", 1)
        storage_object_id = str(UUID(object_name))
    except (ValueError, TypeError, IndexError) as exc:
        raise ValueError("Media cleanup claim contains a malformed object key.") from exc
    if resource_id != parts[2] or storage_object_id != object_name:
        raise ValueError("Media cleanup claim object key is not canonical.")
    if extension not in {"png", "jpg", "webp"}:
        raise ValueError("Media cleanup claim contains an unsupported object extension.")
    attempts, maximum = event.get("attempts"), event.get("max_attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 8:
        raise ValueError("Media cleanup claim contains an invalid attempt counter.")
    if not isinstance(maximum, int) or maximum != 8:
        raise ValueError("Media cleanup claim contains an invalid retry limit.")
    try:
        claim_token = str(UUID(event["claim_token"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Media cleanup claim token is malformed.") from exc
    if claim_token != event["claim_token"]:
        raise ValueError("Media cleanup claim token is not canonical.")


def process_one(settings) -> bool:
    """Claim and delete one object. False means the queue is currently empty."""
    event = claim_media_cleanup(settings, str(uuid4()), CLAIM_LEASE_SECONDS)
    if event is None:
        return False
    try:
        _validate_claim(event)
        plan = plan_media_cleanup(
            authenticated_owner_id=event["owner_id"],
            asset={
                "id": event["asset_id"],
                "owner_id": event["owner_id"],
                "status": "cleanup_pending",
                "bucket": event["bucket"],
                "storage_path": event["storage_path"],
            },
            exact_object_is_referenced=False,
        )
        delete_private_media_object(settings, plan)
        complete_media_cleanup(settings, event)
        logger.info("Deleted private media asset %s", event["asset_id"])
    except Exception as exc:
        raw_attempt = event.get("attempts", 1)
        attempt = raw_attempt if isinstance(raw_attempt, int) and not isinstance(raw_attempt, bool) and raw_attempt > 0 else 1
        delay = min(MAX_RETRY_DELAY_SECONDS, 30 * (2 ** max(0, attempt - 1)))
        try:
            outcome = retry_media_cleanup(settings, event, delay)
            logger.warning(
                "Private media cleanup deferred for asset %s (attempt %s, outcome %s, error %s)",
                event.get("asset_id", "unknown"), attempt, outcome.get("event_status"), type(exc).__name__,
            )
        except Exception as retry_exc:
            # Leave the lease to expire; never acknowledge an uncertain side effect.
            logger.error(
                "Could not schedule private media cleanup retry for asset %s (%s)",
                event.get("asset_id", "unknown"), type(retry_exc).__name__,
            )
    return True


def main():
    global _running
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    settings = get_settings()
    logger.info("Private media cleanup worker started")
    while _running:
        try:
            found = process_one(settings)
        except Exception as exc:
            logger.error("Private media cleanup poll failed (%s)", type(exc).__name__)
            found = False
        if not found and _running:
            time.sleep(POLL_INTERVAL_SECONDS)
    logger.info("Private media cleanup worker stopped gracefully")


if __name__ == "__main__":
    main()
