"""Server-only plan approval and inert assignment operations."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class PlanOperationsUnavailable(RuntimeError):
    pass


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise PlanOperationsUnavailable("Plan operations are not configured.")
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _request(settings: Settings, method: str, path: str, *, params=None, payload=None) -> Any:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.request(
                method,
                f"{settings.supabase_url.rstrip('/')}/rest/v1/{path}",
                params=params,
                json=payload,
                headers=_headers(settings),
            )
            response.raise_for_status()
            return response.json() if response.content else []
    except PlanOperationsUnavailable:
        raise
    except Exception as exc:
        raise PlanOperationsUnavailable("Plan operations storage is temporarily unavailable.") from exc


def _one_rpc_row(result: Any) -> dict[str, Any]:
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise PlanOperationsUnavailable("Plan operation returned an invalid result.")
    return result[0]


def approve_plan_draft(
    settings: Settings, *, draft_id: UUID, actor_id: UUID, reason: str
) -> dict[str, Any]:
    result = _one_rpc_row(_request(
        settings, "POST", "rpc/approve_plan_catalog_draft",
        payload={
            "p_draft_id": str(draft_id),
            "p_actor_user_id": str(actor_id),
            "p_approval_reason": reason,
        },
    ))
    approved_id = UUID(str(result.get("approved_plan_version_id")))
    rows = _request(
        settings, "GET", "approved_plan_versions",
        params={
            "select": "id,source_draft_id,plan_code,plan_version,display_name,billing_period,period_days,credits_per_period,price_minor,currency,limits_json,features_json,approved_by,approval_reason,approved_at",
            "id": f"eq.{approved_id}",
            "limit": "1",
        },
    )
    if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("approved_by")) != str(actor_id):
        raise PlanOperationsUnavailable("Approved plan read-back verification failed.")
    return {"approved_plan": rows[0], "replayed": bool(result.get("replayed"))}


def create_pending_assignment(
    settings: Settings, *, user_id: UUID, approved_plan_version_id: UUID,
    assignment_source: str, source_reference: str, idempotency_key: str,
    starts_at: datetime, ends_at: datetime, actor_id: UUID, reason: str,
) -> dict[str, Any]:
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise ValueError("Timezone-aware assignment dates are required.")
    starts_at = starts_at.astimezone(timezone.utc)
    ends_at = ends_at.astimezone(timezone.utc)
    if ends_at <= starts_at:
        raise ValueError("Assignment end must be after its start.")

    result = _one_rpc_row(_request(
        settings, "POST", "rpc/create_pending_user_plan_assignment",
        payload={
            "p_user_id": str(user_id),
            "p_approved_plan_version_id": str(approved_plan_version_id),
            "p_assignment_source": assignment_source,
            "p_source_reference": source_reference,
            "p_idempotency_key": idempotency_key,
            "p_starts_at": starts_at.isoformat(),
            "p_ends_at": ends_at.isoformat(),
            "p_actor_user_id": str(actor_id),
            "p_reason": reason,
        },
    ))
    assignment_id = UUID(str(result.get("assignment_id")))
    rows = _request(
        settings, "GET", "user_plan_assignments",
        params={
            "select": "id,user_id,approved_plan_version_id,assignment_source,source_reference,idempotency_key,status,starts_at,ends_at,created_by,created_at,metadata",
            "id": f"eq.{assignment_id}",
            "limit": "1",
        },
    )
    if (
        not isinstance(rows, list) or len(rows) != 1
        or str(rows[0].get("user_id")) != str(user_id)
        or str(rows[0].get("approved_plan_version_id")) != str(approved_plan_version_id)
        or str(rows[0].get("created_by")) != str(actor_id)
        or rows[0].get("status") != "pending"
    ):
        raise PlanOperationsUnavailable("Pending assignment read-back verification failed.")
    return {"assignment": rows[0], "replayed": bool(result.get("replayed"))}
