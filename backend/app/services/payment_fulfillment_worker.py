"""Dormant orchestration for payment fulfillment.

This module is intentionally not registered as a FastAPI startup task, route,
or scheduler. A future trusted scheduler may invoke one bounded batch after
operational approval. Ambiguous fulfillment outcomes are never failed blindly:
the atomic database RPC is replay-safe and the next lease can safely reconcile.
"""
from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.services import payment_orders


def run_payment_fulfillment_batch(
    settings: Settings,
    *,
    lease_seconds: int = 120,
    batch_size: int = 5,
) -> dict[str, Any]:
    """Process one bounded claim batch without activating a background worker."""
    claims = payment_orders.claim_payment_fulfillment(
        settings, lease_seconds=lease_seconds, batch_size=batch_size,
    )
    summary: dict[str, Any] = {
        "claimed": len(claims),
        "completed": 0,
        "replayed": 0,
        "retry_queued": 0,
        "manual_review": 0,
        "lease_lost": 0,
        "outcome_unknown": 0,
        "items": [],
    }

    for claim in claims:
        fulfillment_id = claim["fulfillment_id"]
        lease_token = claim["lease_token"]
        item: dict[str, Any] = {"fulfillment_id": str(fulfillment_id)}
        try:
            result = payment_orders.fulfill_payment_order(
                settings,
                fulfillment_id=fulfillment_id,
                lease_token=lease_token,
            )
        except (payment_orders.PaymentOrderConflict, payment_orders.PaymentOrderNotFound) as exc:
            # These are explicit, deterministic RPC rejections. The fenced fail
            # RPC still decides whether this worker owns the lease.
            try:
                state = payment_orders.fail_payment_fulfillment(
                    settings,
                    fulfillment_id=fulfillment_id,
                    lease_token=lease_token,
                    error_code=(
                        "fulfillment_conflict"
                        if isinstance(exc, payment_orders.PaymentOrderConflict)
                        else "fulfillment_not_found"
                    ),
                )
            except Exception:
                # Even the failure transition may have an ambiguous outcome.
                summary["outcome_unknown"] += 1
                item["status"] = "outcome_unknown"
            else:
                counter = {"queued": "retry_queued", "manual_review": "manual_review", "lease_lost": "lease_lost"}[state]
                summary[counter] += 1
                item["status"] = state
            summary["items"].append(item)
            continue
        except Exception:
            # A timeout, connection reset, malformed response, or unexpected
            # exception may occur after the DB transaction committed. Do not
            # call fail_payment_fulfillment: allow replay/reclaim to reconcile.
            summary["outcome_unknown"] += 1
            item["status"] = "outcome_unknown"
            summary["items"].append(item)
            continue

        summary["completed"] += 1
        if result["replayed"]:
            summary["replayed"] += 1
        item.update({
            "status": "completed",
            "purchase_type": result["purchase_type"],
            "replayed": result["replayed"],
        })
        summary["items"].append(item)

    return summary
