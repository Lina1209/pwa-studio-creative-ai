"""Server-only access to the append-only administrative audit RPCs."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class AdminAuditUnavailable(RuntimeError):
    pass


_ALLOWED_ACTIONS = {
    "admin.access", "admin.permission.denied", "admin.user.view",
    "admin.support.view", "admin.tariff.change.requested",
    "admin.tariff.change.approved", "admin.finance.operation.requested",
    "admin.finance.operation.approved", "admin.finance.operation.executed",
    "admin.security.settings.changed",
}
_ALLOWED_OUTCOMES = {"allowed", "denied", "requested", "approved", "executed", "failed"}
_ALLOWED_RESOURCES = {"platform", "user", "support_ticket", "tariff", "payment", "credit_wallet", "permission", "security_setting"}


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise AdminAuditUnavailable("Administrative audit storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _rpc(settings: Settings, name: str, payload: dict[str, Any]) -> Any:
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
                json=payload,
                headers=_headers(settings),
            )
            response.raise_for_status()
            return response.json()
    except AdminAuditUnavailable:
        raise
    except Exception as exc:
        raise AdminAuditUnavailable("Administrative audit storage is temporarily unavailable.") from exc


def record_admin_audit_event(
    settings: Settings, *, actor_user_id: UUID, action: str, outcome: str,
    resource_type: str, resource_id: UUID | None = None,
    correlation_id: UUID | None = None, reason: str | None = None,
) -> str:
    if not isinstance(actor_user_id, UUID):
        raise ValueError("Verified actor UUID is required.")
    if action not in _ALLOWED_ACTIONS or outcome not in _ALLOWED_OUTCOMES or resource_type not in _ALLOWED_RESOURCES:
        raise ValueError("Unsupported administrative audit event.")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 500):
        raise ValueError("Audit reason is invalid.")
    result = _rpc(settings, "record_admin_audit_event", {
        "p_actor_user_id": str(actor_user_id),
        "p_action": action,
        "p_outcome": outcome,
        "p_resource_type": resource_type,
        "p_resource_id": str(resource_id) if resource_id else None,
        "p_correlation_id": str(correlation_id) if correlation_id else None,
        "p_reason": reason,
    })
    if not isinstance(result, str) or not result:
        raise AdminAuditUnavailable("Administrative audit write returned an invalid response.")
    return result


def get_admin_audit_events(
    settings: Settings, *, before: datetime | None = None, limit: int = 100,
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 200:
        raise ValueError("Audit page limit must be between 1 and 200.")
    if before is not None:
        if before.tzinfo is None:
            raise ValueError("Timezone-aware audit cursor is required.")
        before = before.astimezone(timezone.utc)
    result = _rpc(settings, "read_admin_audit_events", {
        "p_before": before.isoformat() if before else None,
        "p_limit": limit,
    })
    if not isinstance(result, list) or len(result) > limit:
        raise AdminAuditUnavailable("Administrative audit read returned an invalid page.")
    safe_events: list[dict[str, Any]] = []
    required = {"id", "occurred_at", "actor_user_id", "action", "outcome", "resource_type"}
    for row in result:
        if not isinstance(row, dict) or not required.issubset(row):
            raise AdminAuditUnavailable("Administrative audit event is malformed.")
        if row["action"] not in _ALLOWED_ACTIONS or row["outcome"] not in _ALLOWED_OUTCOMES or row["resource_type"] not in _ALLOWED_RESOURCES:
            raise AdminAuditUnavailable("Administrative audit event contains unsupported metadata.")
        try:
            UUID(str(row["id"]))
            UUID(str(row["actor_user_id"]))
            timestamp = datetime.fromisoformat(str(row["occurred_at"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("naive timestamp")
        except (ValueError, TypeError, AttributeError) as exc:
            raise AdminAuditUnavailable("Administrative audit event identity is invalid.") from exc
        reason = row.get("reason")
        if reason is not None and (not isinstance(reason, str) or len(reason) > 500):
            raise AdminAuditUnavailable("Administrative audit reason is invalid.")
        safe_events.append({
            "id": str(row["id"]), "occurred_at": str(row["occurred_at"]),
            "actor_user_id": str(row["actor_user_id"]), "action": row["action"],
            "outcome": row["outcome"], "resource_type": row["resource_type"],
            "resource_id": row.get("resource_id"), "correlation_id": row.get("correlation_id"),
            "reason": reason,
        })
    return safe_events
