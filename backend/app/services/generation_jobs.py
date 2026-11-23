from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.services.pricing_service import PricingError, canonical_request_hash, verify_pricing_quote


class GenerationJobsNotConfiguredError(RuntimeError):
    pass


class GenerationJobsServiceError(RuntimeError):
    pass


class GenerationPricingQuoteConflictError(GenerationJobsServiceError):
    """An idempotency key was already bound to a different quote request."""



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


def create_scene_generation_job(
    settings: Settings,
    *,
    user_id: UUID,
    studio_scene_id: UUID,
    job_type: str,
    provider: str,
    model: str,
    idempotency_key: str,
    request_hash: str,
    request_snapshot: dict[str, Any] | None = None,
    pricing_snapshot: dict[str, Any] | None = None,
) -> GenerationJobCreateResult:
    """Create a job for an owned Mini Movie Studio scene via the atomic RPC.

    The user_id must come from the verified server-side auth dependency. The
    database RPC checks scene ownership and the composite FK closes race windows.
    Studio project IDs are deliberately not passed as public.projects IDs.
    """
    if not settings.generation_jobs_enabled:
        raise GenerationJobsNotConfiguredError(
            "Generation jobs are not enabled on this server."
        )
    headers = _headers(settings)
    payload = {
        "p_user_id": str(user_id),
        "p_studio_scene_id": str(studio_scene_id),
        "p_job_type": job_type,
        "p_provider": provider,
        "p_model": model,
        "p_idempotency_key": idempotency_key,
        "p_request_hash": request_hash,
        "p_request_snapshot": request_snapshot or {},
        "p_pricing_snapshot": pricing_snapshot or {},
    }
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "create_scene_generation_job_with_outbox"
    )
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
            f"Could not create scene generation job (HTTP {status_code})."
        ) from exc

    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise GenerationJobsServiceError(
            "The scene job creation service returned an invalid response."
        )
    row = data[0]
    try:
        return GenerationJobCreateResult(
            job_id=UUID(str(row["job_id"])),
            event_id=UUID(str(row["event_id"])) if row.get("event_id") else None,
            created=bool(row["created"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GenerationJobsServiceError(
            "The scene job creation service returned an incomplete response."
        ) from exc


@dataclass(frozen=True)
class CreditedGenerationJobCreateResult:
    job_id: UUID
    event_id: UUID
    hold_id: UUID
    available_credits: int
    reserved_credits: int
    created: bool
    replayed: bool


def create_credited_generation_job(
    settings: Settings,
    *,
    user_id: UUID,
    project_id: UUID | None,
    studio_scene_id: UUID | None,
    job_type: str,
    provider: str,
    model: str,
    idempotency_key: str,
    request_hash: str,
    request_snapshot: dict[str, Any],
    quote_snapshot: dict[str, Any],
) -> CreditedGenerationJobCreateResult:
    """Verify a signed server quote before atomically admitting a credited job."""
    if not settings.generation_jobs_enabled:
        raise GenerationJobsNotConfiguredError(
            "Generation jobs are not enabled on this server."
        )
    if not isinstance(request_snapshot, dict):
        raise GenerationJobsServiceError("Generation request snapshot must be an object.")
    try:
        if canonical_request_hash(request_snapshot) != request_hash:
            raise PricingError("Generation request hash does not match its canonical snapshot.")
        quote = verify_pricing_quote(
            quote_snapshot,
            secret=settings.pricing_quote_signing_secret,
            user_id=user_id,
            job_type=job_type,
            provider=provider,
            model=model,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            project_id=project_id,
            studio_scene_id=studio_scene_id,
        )
    except PricingError as exc:
        raise GenerationJobsServiceError("The server pricing quote is invalid or expired.") from exc
    credit_amount = quote.amount
    quote_snapshot = quote.snapshot()

    headers = _headers(settings)
    payload = {
        "p_user_id": str(user_id),
        "p_project_id": str(project_id) if project_id else None,
        "p_studio_scene_id": str(studio_scene_id) if studio_scene_id else None,
        "p_job_type": job_type,
        "p_provider": provider,
        "p_model": model,
        "p_idempotency_key": idempotency_key,
        "p_request_hash": request_hash,
        "p_request_snapshot": request_snapshot,
        "p_quote_snapshot": quote_snapshot,
        "p_credit_amount": credit_amount,
    }
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "create_credited_generation_job_with_outbox"
    )
    try:
        with httpx.Client(timeout=12.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", "unavailable")
        raise GenerationJobsServiceError(
            f"Could not admit credited generation job (HTTP {status_code})."
        ) from exc

    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise GenerationJobsServiceError("The credited job service returned an invalid response.")
    row = data[0]
    try:
        available = row["available_credits"]
        reserved = row["reserved_credits"]
        created = row["created"]
        replayed = row["replayed"]
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in (available, reserved)):
            raise ValueError("wallet balances")
        if not isinstance(created, bool) or not isinstance(replayed, bool):
            raise ValueError("operation flags")
        if created == replayed:
            raise ValueError("operation flags are inconsistent")
        return CreditedGenerationJobCreateResult(
            job_id=UUID(str(row["job_id"])),
            event_id=UUID(str(row["event_id"])),
            hold_id=UUID(str(row["hold_id"])),
            available_credits=available,
            reserved_credits=reserved,
            created=created,
            replayed=replayed,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GenerationJobsServiceError(
            "The credited job service returned incomplete or invalid metadata."
        ) from exc


@dataclass(frozen=True)
class PersistedPricingQuote:
    snapshot: dict[str, Any]
    created: bool
    expired: bool


def store_pricing_quote(
    settings: Settings,
    *,
    user_id: UUID,
    idempotency_key: str,
    request_hash: str,
    job_type: str,
    provider: str,
    model: str,
    project_id: UUID | None,
    studio_scene_id: UUID | None,
    quote_snapshot: dict[str, Any],
) -> PersistedPricingQuote:
    """Persist one immutable quote per owner/idempotency key via service-role RPC."""
    headers = _headers(settings)
    if not isinstance(quote_snapshot, dict):
        raise GenerationJobsServiceError("Pricing quote snapshot must be an object.")
    try:
        quote_id = UUID(str(quote_snapshot["quote_id"]))
        expires_at = quote_snapshot["expires_at"]
        if not isinstance(expires_at, str) or len(expires_at) > 64:
            raise ValueError("expiry")
    except (KeyError, TypeError, ValueError) as exc:
        raise GenerationJobsServiceError("Pricing quote snapshot is incomplete.") from exc
    payload = {
        "p_quote_id": str(quote_id),
        "p_user_id": str(user_id),
        "p_idempotency_key": idempotency_key,
        "p_request_hash": request_hash,
        "p_job_type": job_type,
        "p_provider": provider,
        "p_model": model,
        "p_project_id": str(project_id) if project_id else None,
        "p_studio_scene_id": str(studio_scene_id) if studio_scene_id else None,
        "p_quote_snapshot": quote_snapshot,
        "p_expires_at": expires_at,
    }
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/store_generation_pricing_quote"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", "unavailable")
        if status_code in {400, 409}:
            raise GenerationPricingQuoteConflictError(
                "Pricing quote idempotency key conflicts with an earlier request."
            ) from exc
        raise GenerationJobsServiceError(
            f"Could not persist pricing quote (HTTP {status_code})."
        ) from exc
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise GenerationJobsServiceError("Pricing quote persistence returned an invalid response.")
    row = data[0]
    snapshot = row.get("quote_snapshot")
    created = row.get("created")
    expired = row.get("expired")
    if not isinstance(snapshot, dict) or not isinstance(created, bool) or not isinstance(expired, bool):
        raise GenerationJobsServiceError("Pricing quote persistence returned incomplete metadata.")
    return PersistedPricingQuote(snapshot=snapshot, created=created, expired=expired)



@dataclass(frozen=True)
class PlanQuotaReservationResult:
    reservation_id: UUID
    feature_key: str
    feature_limit: int
    used_units: int
    remaining_units: int
    status: str
    replayed: bool


@dataclass(frozen=True)
class PlanCreditedGenerationJobCreateResult:
    job_id: UUID
    event_id: UUID
    hold_id: UUID
    available_credits: int
    reserved_credits: int
    created: bool
    replayed: bool
    quota_reservations: tuple[PlanQuotaReservationResult, ...]


def _expected_plan_quota_features(job_type: str) -> tuple[str, ...]:
    mapping = {
        "image_generation": ("daily_image_generations", "monthly_image_generations"),
        "video_generation": ("daily_video_generations", "monthly_video_generations"),
        "audio_generation": ("daily_audio_generations", "monthly_audio_generations"),
        "speech_generation": ("daily_audio_generations", "monthly_audio_generations"),
        "ai_processing": (
            "daily_ai_requests", "monthly_ai_requests", "max_concurrent_ai_requests"
        ),
    }
    try:
        return mapping[job_type]
    except KeyError as exc:
        raise GenerationJobsServiceError(
            "This generation type has no approved customer-plan quota mapping."
        ) from exc


def create_plan_credited_generation_job(
    settings: Settings,
    *,
    user_id: UUID,
    project_id: UUID | None,
    studio_scene_id: UUID | None,
    job_type: str,
    provider: str,
    model: str,
    idempotency_key: str,
    request_hash: str,
    request_snapshot: dict[str, Any],
    quote_snapshot: dict[str, Any],
) -> PlanCreditedGenerationJobCreateResult:
    """Verify a signed quote, then atomically reserve plan quota, credits, job and outbox."""
    if not settings.generation_jobs_enabled:
        raise GenerationJobsNotConfiguredError(
            "Generation jobs are not enabled on this server."
        )
    if not isinstance(user_id, UUID) or (project_id is not None and not isinstance(project_id, UUID)):
        raise GenerationJobsServiceError("Verified owner and project identities are required.")
    if studio_scene_id is not None and not isinstance(studio_scene_id, UUID):
        raise GenerationJobsServiceError("Verified studio scene identity is required.")
    if project_id is not None and studio_scene_id is not None:
        raise GenerationJobsServiceError("A generation job cannot target two project types.")
    if not isinstance(request_snapshot, dict):
        raise GenerationJobsServiceError("Generation request snapshot must be an object.")

    expected_features = _expected_plan_quota_features(job_type)
    try:
        if canonical_request_hash(request_snapshot) != request_hash:
            raise PricingError("Generation request hash does not match its canonical snapshot.")
        quote = verify_pricing_quote(
            quote_snapshot,
            secret=settings.pricing_quote_signing_secret,
            user_id=user_id,
            job_type=job_type,
            provider=provider,
            model=model,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            project_id=project_id,
            studio_scene_id=studio_scene_id,
        )
    except PricingError as exc:
        raise GenerationJobsServiceError(
            "The server pricing quote is invalid or expired."
        ) from exc

    payload = {
        "p_user_id": str(user_id),
        "p_project_id": str(project_id) if project_id else None,
        "p_studio_scene_id": str(studio_scene_id) if studio_scene_id else None,
        "p_job_type": job_type,
        "p_provider": provider,
        "p_model": model,
        "p_idempotency_key": idempotency_key,
        "p_request_hash": request_hash,
        "p_request_snapshot": request_snapshot,
        "p_quote_snapshot": quote.snapshot(),
        "p_credit_amount": quote.amount,
    }
    url = (
        f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/"
        "create_plan_credited_generation_job_with_outbox"
    )
    headers = _headers(settings)
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", "unavailable")
        raise GenerationJobsServiceError(
            f"Could not atomically admit plan-based generation (HTTP {status_code})."
        ) from exc

    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise GenerationJobsServiceError(
            "The plan-based generation service returned an invalid response."
        )
    row = data[0]
    try:
        available = row["available_credits"]
        reserved = row["reserved_credits"]
        created = row["created"]
        replayed = row["replayed"]
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in (available, reserved)):
            raise ValueError("wallet balances")
        if not isinstance(created, bool) or not isinstance(replayed, bool) or created == replayed:
            raise ValueError("operation flags")
        raw_quotas = row["quota_reservations"]
        if not isinstance(raw_quotas, list) or len(raw_quotas) != len(expected_features):
            raise ValueError("quota reservation list")
        parsed_quotas: list[PlanQuotaReservationResult] = []
        for item in raw_quotas:
            if not isinstance(item, dict):
                raise ValueError("quota reservation item")
            feature = item["feature_key"]
            if feature not in expected_features:
                raise ValueError("unexpected quota feature")
            limit = item["feature_limit"]
            used = item["used_units"]
            remaining = item["remaining_units"]
            status = item["status"]
            item_replayed = item["replayed"]
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                   for value in (limit, used, remaining)):
                raise ValueError("quota totals")
            if used > limit or remaining != max(limit - used, 0):
                raise ValueError("inconsistent quota totals")
            if status not in {"reserved", "completed", "released"} or not isinstance(item_replayed, bool):
                raise ValueError("quota lifecycle")
            parsed_quotas.append(PlanQuotaReservationResult(
                reservation_id=UUID(str(item["reservation_id"])),
                feature_key=feature,
                feature_limit=limit,
                used_units=used,
                remaining_units=remaining,
                status=status,
                replayed=item_replayed,
            ))
        if {item.feature_key for item in parsed_quotas} != set(expected_features):
            raise ValueError("missing quota dimension")
        return PlanCreditedGenerationJobCreateResult(
            job_id=UUID(str(row["job_id"])),
            event_id=UUID(str(row["event_id"])),
            hold_id=UUID(str(row["hold_id"])),
            available_credits=available,
            reserved_credits=reserved,
            created=created,
            replayed=replayed,
            quota_reservations=tuple(parsed_quotas),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GenerationJobsServiceError(
            "The plan-based generation service returned incomplete or inconsistent metadata."
        ) from exc
