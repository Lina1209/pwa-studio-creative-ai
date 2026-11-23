"""PostgreSQL-backed admission gate for authenticated synchronous AI requests.

This is a distributed operational rate/concurrency limit. It is deliberately
separate from customer credits, subscriptions, and provider-cost accounting.
"""
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx

from app.core.config import Settings


class AIAdmissionUnavailable(RuntimeError):
    pass


class AIAdmissionRejected(RuntimeError):
    def __init__(self, reason: str, retry_after_seconds: int):
        self.reason = reason
        self.retry_after_seconds = max(1, min(int(retry_after_seconds), 300))
        super().__init__("AI request capacity is currently limited.")


@dataclass(frozen=True)
class AIAdmissionReservation:
    request_id: UUID
    user_id: UUID


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise AIAdmissionUnavailable("AI admission storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def reserve_ai_request(
    settings: Settings, *, user_id: UUID, endpoint: str
) -> AIAdmissionReservation:
    if endpoint not in {"chat", "prompts", "movie_script", "movie_director", "movie_storyboard", "vision"}:
        raise ValueError("Unsupported AI endpoint.")
    request_id = uuid4()
    headers = _headers(settings)
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/reserve_ai_request"
    payload = {
        "p_user_id": str(user_id),
        "p_request_id": str(request_id),
        "p_endpoint": endpoint,
        "p_max_per_minute": settings.ai_max_requests_per_minute_per_user,
        "p_max_concurrent": settings.ai_max_concurrent_requests_per_user,
        "p_max_global_concurrent": settings.ai_max_global_concurrent_requests,
        "p_max_per_day": settings.ai_max_requests_per_day_per_user,
        "p_max_global_per_day": settings.ai_max_requests_per_day_global,
        "p_max_per_month": settings.ai_max_requests_per_month_per_user,
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise AIAdmissionUnavailable("AI admission check is temporarily unavailable.") from exc

    if not isinstance(data, dict) or not isinstance(data.get("admitted"), bool):
        raise AIAdmissionUnavailable("AI admission service returned an invalid response.")
    if not data["admitted"]:
        reason = data.get("reason")
        retry = data.get("retry_after_seconds", 10)
        if isinstance(retry, bool) or not isinstance(retry, int):
            retry = 10
        raise AIAdmissionRejected(
            reason if reason in {"rate_limited", "concurrency_limited", "global_concurrency_limited", "daily_user_limit", "daily_global_limit", "monthly_user_limit"} else "limited",
            retry,
        )
    if data.get("duplicate") is True:
        # The API always creates a fresh server-side request UUID. A duplicate
        # here indicates unexpected replay and must not launch a second provider call.
        raise AIAdmissionRejected("duplicate_request", 10)
    return AIAdmissionReservation(request_id=request_id, user_id=user_id)


def finish_ai_request(
    settings: Settings, reservation: AIAdmissionReservation, *, completed: bool
) -> None:
    outcome = "completed" if completed else "released"
    headers = _headers(settings)
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/finish_ai_request"
    payload = {
        "p_user_id": str(reservation.user_id),
        "p_request_id": str(reservation.request_id),
        "p_outcome": outcome,
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise AIAdmissionUnavailable("AI admission reservation could not be finalized.") from exc
    if data is not True:
        raise AIAdmissionUnavailable("AI admission reservation could not be finalized.")
