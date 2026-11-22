from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class GenerationJobsNotConfiguredError(RuntimeError):
    pass


class GenerationJobsServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationJobCreateResult:
    job_id: UUID
    event_id: UUID | None
    created: bool


_JOB_STATUS_FIELDS = (
    "id,project_id,job_type,provider,model,status,attempt_count,max_attempts,"
    "last_error_code,created_at,updated_at,started_at,completed_at"
)


def _headers(settings: Settings) -> dict[str, str]:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise GenerationJobsNotConfiguredError(
            "Generation job storage is not configured on the server."
        )

    headers = {
        "apikey": key,
        "Content-Type": "application/json",
    }
    # Supabase sb_secret_* keys are API keys, not JWTs. Legacy service_role
    # JWTs also need the Authorization header.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def create_generation_job(
    settings: Settings,
    *,
    user_id: UUID,
    project_id: UUID | None,
    job_type: str,
    provider: str,
    model: str,
    idempotency_key: str,
    request_hash: str,
    request_snapshot: dict[str, Any] | None = None,
    pricing_snapshot: dict[str, Any] | None = None,
) -> GenerationJobCreateResult:
    """Call the trusted atomic job+outbox RPC. Never accept client credentials."""
    if not settings.generation_jobs_enabled:
        raise GenerationJobsNotConfiguredError(
            "Generation jobs are not enabled on this server."
        )

    headers = _headers(settings)
    payload = {
        "p_user_id": str(user_id),
        "p_project_id": str(project_id) if project_id else None,
        "p_job_type": job_type,
        "p_provider": provider,
        "p_model": model,
        "p_idempotency_key": idempotency_key,
        "p_request_hash": request_hash,
        "p_request_snapshot": request_snapshot or {},
        "p_pricing_snapshot": pricing_snapshot or {},
    }
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/create_generation_job_with_outbox"

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except GenerationJobsNotConfiguredError:
        raise
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", "unavailable")
        raise GenerationJobsServiceError(
            f"Could not create generation job (HTTP {status_code})."
        ) from exc

    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise GenerationJobsServiceError("The job creation service returned an invalid response.")

    row = data[0]
    try:
        return GenerationJobCreateResult(
            job_id=UUID(str(row["job_id"])),
            event_id=UUID(str(row["event_id"])) if row.get("event_id") else None,
            created=bool(row["created"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GenerationJobsServiceError(
            "The job creation service returned an incomplete response."
        ) from exc


def get_generation_job(
    settings: Settings,
    *,
    user_id: UUID,
    job_id: UUID,
) -> dict[str, Any] | None:
    """Read a job only when both its id and authenticated owner match."""
    if not settings.generation_jobs_enabled:
        raise GenerationJobsNotConfiguredError(
            "Generation jobs are not enabled on this server."
        )

    headers = _headers(settings)
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/generation_jobs"
    params = {
        "id": f"eq.{job_id}",
        "user_id": f"eq.{user_id}",
        "select": _JOB_STATUS_FIELDS,
        "limit": "1",
    }

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
    except GenerationJobsNotConfiguredError:
        raise
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", "unavailable")
        raise GenerationJobsServiceError(
            f"Could not read generation job (HTTP {status_code})."
        ) from exc

    if not isinstance(data, list):
        raise GenerationJobsServiceError("The job status service returned an invalid response.")
    if not data:
        return None
    if len(data) != 1 or not isinstance(data[0], dict):
        raise GenerationJobsServiceError("The job status service returned an ambiguous response.")
    return data[0]
