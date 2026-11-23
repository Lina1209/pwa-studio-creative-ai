"""Server-only bridge to atomic customer-plan quota reservations."""
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class PlanQuotaUnavailable(RuntimeError):
    pass


class PlanQuotaRejected(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PlanQuotaReservation:
    reservation_id: UUID
    assignment_id: UUID
    feature_key: str
    feature_limit: int
    used_units: int
    remaining_units: int
    status: str
    replayed: bool


ALLOWED_FEATURES = frozenset({
    "daily_ai_requests", "monthly_ai_requests", "max_concurrent_ai_requests",
    "daily_image_generations", "monthly_image_generations",
    "daily_video_generations", "monthly_video_generations",
    "daily_audio_generations", "monthly_audio_generations",
})


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise PlanQuotaUnavailable("Plan quota storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _rpc(settings: Settings, name: str, payload: dict[str, Any]) -> Any:
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
                json=payload,
                headers=_headers(settings),
            )
            if response.status_code >= 400:
                if 400 <= response.status_code < 500:
                    try:
                        error = response.json()
                    except ValueError:
                        error = {}
                    code = error.get("code") if isinstance(error, dict) else None
                    if code in {"42501", "54000", "P0002", "23514", "23505", "22023"}:
                        raise PlanQuotaRejected("plan_quota_denied")
                    if response.status_code in (400, 403, 404, 409, 422):
                        raise PlanQuotaRejected("plan_quota_denied")
                response.raise_for_status()
            return response.json()
    except PlanQuotaRejected:
        raise
    except Exception as exc:
        raise PlanQuotaUnavailable("Plan quota service is temporarily unavailable.") from exc


def reserve_plan_quota(
    settings: Settings, *, user_id: UUID, request_id: UUID,
    feature_key: str, operation_key: str, units: int = 1,
) -> PlanQuotaReservation:
    if not isinstance(user_id, UUID) or not isinstance(request_id, UUID):
        raise ValueError("Verified user and request UUIDs are required.")
    if feature_key not in ALLOWED_FEATURES:
        raise ValueError("Unsupported plan quota feature.")
    if not isinstance(operation_key, str) or not 8 <= len(operation_key) <= 200:
        raise ValueError("Plan quota idempotency key is invalid.")
    if isinstance(units, bool) or not isinstance(units, int) or not 1 <= units <= 10000:
        raise ValueError("Plan quota units are invalid.")

    data = _rpc(settings, "reserve_plan_quota", {
        "p_user_id": str(user_id),
        "p_request_id": str(request_id),
        "p_feature_key": feature_key,
        "p_operation_key": operation_key,
        "p_units": units,
    })
    if isinstance(data, list):
        if len(data) != 1:
            raise PlanQuotaUnavailable("Plan quota RPC returned an invalid result.")
        data = data[0]
    if not isinstance(data, dict):
        raise PlanQuotaUnavailable("Plan quota RPC returned an invalid result.")
    try:
        reservation_id = UUID(str(data["reservation_id"]))
        assignment_id = UUID(str(data["assignment_id"]))
        feature_limit = _integer(data["feature_limit"], "feature limit")
        used_units = _integer(data["used_units"], "used units")
        remaining_units = _integer(data["remaining_units"], "remaining units")
        status = data["status"]
        replayed = data["replayed"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PlanQuotaUnavailable("Plan quota RPC returned malformed fields.") from exc
    if status not in {"reserved", "completed"} or not isinstance(replayed, bool):
        raise PlanQuotaUnavailable("Plan quota RPC returned invalid reservation state.")
    if used_units > feature_limit or remaining_units != max(feature_limit - used_units, 0):
        raise PlanQuotaUnavailable("Plan quota RPC returned inconsistent usage totals.")
    return PlanQuotaReservation(
        reservation_id, assignment_id, feature_key, feature_limit,
        used_units, remaining_units, status, replayed,
    )


def finish_plan_quota_reservation(
    settings: Settings, *, user_id: UUID, reservation_id: UUID, completed: bool,
) -> bool:
    if not isinstance(user_id, UUID) or not isinstance(reservation_id, UUID):
        raise ValueError("Verified user and reservation UUIDs are required.")
    if not isinstance(completed, bool):
        raise ValueError("Quota completion outcome must be boolean.")
    data = _rpc(settings, "finish_plan_quota_reservation", {
        "p_user_id": str(user_id),
        "p_reservation_id": str(reservation_id),
        "p_outcome": "completed" if completed else "released",
    })
    if isinstance(data, list):
        if len(data) != 1:
            raise PlanQuotaUnavailable("Plan quota completion returned an invalid result.")
        data = data[0]
    if not isinstance(data, dict) or data.get("status") != ("completed" if completed else "released"):
        raise PlanQuotaUnavailable("Plan quota completion could not be verified.")
    if not isinstance(data.get("replayed"), bool):
        raise PlanQuotaUnavailable("Plan quota completion idempotency metadata is invalid.")
    return data["replayed"]


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlanQuotaUnavailable(f"Plan quota returned invalid {field}.")
    return value
