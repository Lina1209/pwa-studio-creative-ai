"""Read-only effective plan and capability resolver for authenticated studio users.

Only a single time-valid active assignment can grant plan capabilities. Pending,
scheduled, expired, revoked, or ambiguous assignments never grant access.
"""
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class EntitlementsUnavailable(RuntimeError):
    pass


# These dimensions are enforced by the atomic generation admission RPCs.
_ENFORCED_DIMENSIONS = {
    "daily_ai_requests", "monthly_ai_requests", "max_concurrent_ai_requests",
    "daily_image_generations", "monthly_image_generations",
    "daily_video_generations", "monthly_video_generations",
    "daily_audio_generations", "monthly_audio_generations",
    "daily_generation_jobs", "monthly_generation_jobs", "max_parallel_jobs",
    "max_video_seconds", "max_resolution",
}

# Every supported plan dimension is now connected to the transactional admission path.


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise EntitlementsUnavailable("Entitlements storage is not configured.")
    headers = {"apikey": key, "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _get(settings: Settings, table: str, params: dict[str, str]) -> Any:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/{table}",
                params=params,
                headers=_headers(settings),
            )
            response.raise_for_status()
            return response.json() if response.content else []
    except EntitlementsUnavailable:
        raise
    except Exception as exc:
        raise EntitlementsUnavailable("Effective plan information is temporarily unavailable.") from exc


def _utc_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def resolve_user_entitlements(settings: Settings, *, user_id: UUID) -> dict[str, Any]:
    """Resolve only server-owned, active-plan facts and current quota usage."""
    if not isinstance(user_id, UUID):
        raise ValueError("Verified user UUID is required.")

    now = datetime.now(timezone.utc)
    now_text = _utc_datetime(now)
    assignments = _get(
        settings,
        "user_plan_assignments",
        {
            "select": "id,user_id,approved_plan_version_id,starts_at,ends_at,created_at",
            "user_id": f"eq.{user_id}",
            "ends_at": f"gt.{now_text}",
            "order": "starts_at.desc,id.desc",
            "limit": "1001",
        },
    )
    if not isinstance(assignments, list) or len(assignments) > 1000 or any(not isinstance(x, dict) for x in assignments):
        raise EntitlementsUnavailable("Plan assignment query returned invalid or excessive data.")

    events = []
    if assignments:
        assignment_ids = ",".join(str(item.get("id")) for item in assignments)
        events = _get(
            settings,
            "user_plan_assignment_events",
            {
                "select": "id,assignment_id,event_type,occurred_at",
                "assignment_id": f"in.({assignment_ids})",
                "order": "occurred_at.desc,id.desc",
                "limit": "10000",
            },
        )
    if not isinstance(events, list) or len(events) >= 10000 or any(not isinstance(x, dict) for x in events):
        raise EntitlementsUnavailable("Plan assignment lifecycle history is invalid or incomplete.")

    latest_event_by_assignment = {}
    for event in events:
        assignment_id = str(event.get("assignment_id") or "")
        if assignment_id and assignment_id not in latest_event_by_assignment:
            latest_event_by_assignment[assignment_id] = event.get("event_type")

    def _assignment_is_current(item: dict[str, Any]) -> bool:
        try:
            starts_at = datetime.fromisoformat(str(item["starts_at"]).replace("Z", "+00:00"))
            ends_at = datetime.fromisoformat(str(item["ends_at"]).replace("Z", "+00:00"))
            if starts_at.tzinfo is None or ends_at.tzinfo is None:
                raise ValueError("Plan assignment timestamps must include a timezone.")
            return starts_at <= now < ends_at
        except (KeyError, TypeError, ValueError) as exc:
            raise EntitlementsUnavailable("Plan assignment timestamps are invalid.") from exc

    activated = [
        item for item in assignments
        if latest_event_by_assignment.get(str(item.get("id"))) == "activated"
        and _assignment_is_current(item)
    ]
    pending = [
        item for item in assignments
        if latest_event_by_assignment.get(str(item.get("id"))) in {"created", "scheduled"}
    ]

    if len(activated) > 1:
        return {
            "status": "ambiguous_active_assignments",
            "plan": None,
            "features": [],
            "quotas": {},
            "pending_assignment_exists": bool(pending),
            "capabilities_enabled": False,
            "activation_enabled": False,
            "checkout_enabled": False,
            "credits_granted": False,
            "generated_at": now_text,
            "reason": "More than one active assignment exists; access is denied until reviewed.",
        }

    if not activated:
        return {
            "status": "no_active_plan",
            "plan": None,
            "features": [],
            "quotas": {},
            "pending_assignment_exists": bool(pending),
            "capabilities_enabled": False,
            "activation_enabled": False,
            "checkout_enabled": False,
            "credits_granted": False,
            "generated_at": now_text,
            "reason": "No time-valid active plan assignment exists.",
        }

    assignment = activated[0]
    if (
        str(assignment.get("user_id")) != str(user_id)
        or not assignment.get("approved_plan_version_id")
    ):
        raise EntitlementsUnavailable("Active assignment failed ownership verification.")

    approved_id = str(assignment["approved_plan_version_id"])
    plans = _get(
        settings,
        "approved_plan_versions",
        {
            "select": "id,plan_code,plan_version,display_name,billing_period,period_days,credits_per_period,price_minor,currency,limits_json,features_json",
            "id": f"eq.{approved_id}",
            "limit": "1",
        },
    )
    if not isinstance(plans, list) or len(plans) != 1 or not isinstance(plans[0], dict):
        raise EntitlementsUnavailable("Approved plan snapshot could not be verified.")
    plan = plans[0]
    limits = plan.get("limits_json")
    features = plan.get("features_json")
    if str(plan.get("id")) != approved_id or not isinstance(limits, dict) or not isinstance(features, list):
        raise EntitlementsUnavailable("Approved plan snapshot contains invalid data.")
    if any(not isinstance(item, str) for item in features):
        raise EntitlementsUnavailable("Approved plan features contain invalid data.")

    reservations = _get(
        settings,
        "plan_quota_reservations",
        {
            "select": "feature_key,reserved_units,status,period_start",
            "user_id": f"eq.{user_id}",
            "status": "in.(reserved,completed)",
            "limit": "10001",
        },
    )
    if not isinstance(reservations, list) or len(reservations) > 10000 or any(not isinstance(x, dict) for x in reservations):
        raise EntitlementsUnavailable("Quota usage query returned invalid data.")

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_day = day_start + timedelta(days=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    usage: dict[str, int] = {}
    for row in reservations:
        feature = row.get("feature_key")
        units = row.get("reserved_units")
        status = row.get("status")
        period = row.get("period_start")
        if not isinstance(feature, str) or isinstance(units, bool) or not isinstance(units, int) or units < 1:
            raise EntitlementsUnavailable("Quota usage row contains invalid values.")
        if status not in {"reserved", "completed"}:
            raise EntitlementsUnavailable("Quota usage row has an unexpected status.")
        if feature in {"max_concurrent_ai_requests", "max_parallel_jobs"}:
            if status == "reserved":
                usage[feature] = usage.get(feature, 0) + units
            continue
        if not isinstance(period, str):
            raise EntitlementsUnavailable("Quota usage row is missing its period start.")
        if feature.startswith("daily_") and period == day_start.isoformat():
            usage[feature] = usage.get(feature, 0) + units
        elif feature.startswith("monthly_") and period == month_start.isoformat():
            usage[feature] = usage.get(feature, 0) + units

    quotas: dict[str, dict[str, Any]] = {}
    for feature in sorted(_ENFORCED_DIMENSIONS):
        raw_limit = limits.get(feature)
        if feature == "max_resolution":
            if raw_limit is not None and (not isinstance(raw_limit, str) or raw_limit not in {"480p", "720p", "1080p", "4k"}):
                raise EntitlementsUnavailable("Approved plan contains an invalid resolution limit.")
            limit = raw_limit
            used = 0
            remaining = None
        else:
            if raw_limit is not None and (
                isinstance(raw_limit, bool)
                or not isinstance(raw_limit, (int, str))
                or (isinstance(raw_limit, int) and raw_limit < 0)
                or (isinstance(raw_limit, str) and not raw_limit.isdigit())
            ):
                raise EntitlementsUnavailable("Approved plan contains an invalid quota limit.")
            limit = int(raw_limit) if raw_limit is not None else None
            used = usage.get(feature, 0)
            remaining = max(limit - used, 0) if limit is not None else None
        enforced = feature in _ENFORCED_DIMENSIONS
        if feature.startswith("daily_"):
            window_start = day_start.isoformat()
            reset_at = next_day.isoformat()
        elif feature.startswith("monthly_"):
            window_start = month_start.isoformat()
            reset_at = next_month.isoformat()
        elif feature in {"max_concurrent_ai_requests", "max_parallel_jobs"}:
            window_start = None
            reset_at = None
        else:
            window_start = None
            reset_at = None
        quotas[feature] = {
            "limit": limit,
            "used": used,
            "remaining": remaining,
            "enforced": enforced,
            "configured": limit is not None,
            "window_start": window_start,
            "reset_at": reset_at,
        }

    common_job_dimensions = (
        "daily_generation_jobs", "monthly_generation_jobs", "max_parallel_jobs"
    )
    capability_dimensions = {
        "ai": ("ai", (
            "daily_ai_requests", "monthly_ai_requests", "max_concurrent_ai_requests",
            *common_job_dimensions,
        )),
        "image": ("image", (
            "daily_image_generations", "monthly_image_generations",
            *common_job_dimensions,
        )),
        "video": ("video", (
            "daily_video_generations", "monthly_video_generations",
            *common_job_dimensions,
        )),
        "audio": ("audio", (
            "daily_audio_generations", "monthly_audio_generations",
            *common_job_dimensions,
        )),
    }
    capabilities = {}
    for capability, (feature_name, required_dimensions) in capability_dimensions.items():
        included = feature_name in features
        configured = all(
            quotas.get(dimension, {}).get("configured")
            and (quotas[dimension]["limit"] or 0) > 0
            for dimension in required_dimensions
        )
        capabilities[capability] = {
            "available": included and configured,
            "included_in_plan": included,
            "quota_ready": configured,
            "reason": None if included and configured else (
                "feature_not_included" if not included else "required_quota_not_configured"
            ),
        }

    return {
        "status": "active",
        "plan": {
            "id": approved_id,
            "code": plan.get("plan_code"),
            "version": plan.get("plan_version"),
            "name": plan.get("display_name"),
            "billing_period": plan.get("billing_period"),
            "period_days": plan.get("period_days"),
            "credits_per_period": plan.get("credits_per_period"),
            "price_minor": plan.get("price_minor"),
            "currency": plan.get("currency"),
        },
        "assignment": {
            "id": str(assignment["id"]),
            "starts_at": assignment.get("starts_at"),
            "ends_at": assignment.get("ends_at"),
        },
        "features": features,
        "capabilities": capabilities,
        "quotas": quotas,
        "pending_assignment_exists": bool(pending),
        "capabilities_enabled": any(item["available"] for item in capabilities.values()),
        "activation_enabled": False,
        "checkout_enabled": False,
        "credits_granted": False,
        "generated_at": now_text,
    }
