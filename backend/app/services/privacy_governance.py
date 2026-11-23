"""Server-only access to privacy consent, request-intake and transfer-audit RPCs.

Only metadata is sent to the database. Never pass prompts, uploaded bytes, data URLs,
provider payloads, signed URLs, or secrets to this module.
"""
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings


class PrivacyGovernanceUnavailable(RuntimeError):
    pass


def _rpc(settings: Settings, name: str, payload: dict[str, Any]) -> Any:
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise PrivacyGovernanceUnavailable("Privacy governance storage is not configured.")
    headers = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/{name}",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        raise PrivacyGovernanceUnavailable("Privacy governance storage is temporarily unavailable.") from exc


def _uuid(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PrivacyGovernanceUnavailable("Privacy governance returned an invalid identifier.") from exc


def record_consent_event(
    settings: Settings, *, user_id: UUID, consent_scope: str, action: str,
    policy_version: str, consent_version: str, source: str = "web_app",
    correlation_id: UUID | None = None,
) -> str:
    if not isinstance(user_id, UUID):
        raise ValueError("Verified user UUID is required.")
    if consent_scope not in {"privacy_notice", "vision_deepseek"} or action not in {"accepted", "withdrawn"}:
        raise ValueError("Unsupported consent scope or action.")
    if source not in {"web_app", "account_settings"}:
        raise ValueError("Unsupported consent source.")
    if not policy_version or len(policy_version) > 80 or not consent_version or len(consent_version) > 80:
        raise ValueError("Consent versions are invalid.")
    result = _rpc(settings, "record_privacy_consent_event", {
        "p_user_id": str(user_id),
        "p_consent_scope": consent_scope,
        "p_action": action,
        "p_policy_version": policy_version,
        "p_consent_version": consent_version,
        "p_source": source,
        "p_correlation_id": str(correlation_id) if correlation_id else None,
    })
    return _uuid(result)


def get_consent_status(settings: Settings, *, user_id: UUID) -> list[dict[str, Any]]:
    if not isinstance(user_id, UUID):
        raise ValueError("Verified user UUID is required.")
    result = _rpc(settings, "get_privacy_consent_status", {"p_user_id": str(user_id)})
    if not isinstance(result, list) or len(result) > 10:
        raise PrivacyGovernanceUnavailable("Consent status response is malformed.")
    safe: list[dict[str, Any]] = []
    for row in result:
        if not isinstance(row, dict) or row.get("consent_scope") not in {"privacy_notice", "vision_deepseek"}:
            raise PrivacyGovernanceUnavailable("Consent status response is malformed.")
        if row.get("action") not in {"accepted", "withdrawn"}:
            raise PrivacyGovernanceUnavailable("Consent status response is malformed.")
        safe.append({
            "consent_scope": row["consent_scope"],
            "action": row["action"],
            "policy_version": str(row.get("policy_version", "")),
            "consent_version": str(row.get("consent_version", "")),
            "occurred_at": row.get("occurred_at"),
            "event_id": _uuid(row.get("event_id")),
        })
    return safe


def create_privacy_request(
    settings: Settings, *, user_id: UUID, request_type: str, idempotency_key: UUID,
) -> dict[str, Any]:
    if not isinstance(user_id, UUID) or not isinstance(idempotency_key, UUID):
        raise ValueError("Verified user and idempotency UUIDs are required.")
    if request_type not in {"access", "export", "correction", "deletion"}:
        raise ValueError("Unsupported privacy request type.")
    result = _rpc(settings, "create_privacy_request", {
        "p_user_id": str(user_id),
        "p_request_type": request_type,
        "p_idempotency_key": str(idempotency_key),
    })
    if not isinstance(result, dict) or result.get("request_type") != request_type:
        raise PrivacyGovernanceUnavailable("Privacy request response is malformed.")
    status = result.get("status")
    if status not in {"submitted", "in_review", "completed", "rejected", "cancelled"}:
        raise PrivacyGovernanceUnavailable("Privacy request status is invalid.")
    return {
        "id": _uuid(result.get("id")),
        "request_type": request_type,
        "status": status,
        "created_at": result.get("created_at"),
        "duplicate": bool(result.get("duplicate")),
    }


def list_privacy_requests(settings: Settings, *, user_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
    if not isinstance(user_id, UUID) or not 1 <= limit <= 100:
        raise ValueError("Privacy request query is invalid.")
    result = _rpc(settings, "list_privacy_requests_for_user", {
        "p_user_id": str(user_id), "p_limit": limit,
    })
    if not isinstance(result, list) or len(result) > limit:
        raise PrivacyGovernanceUnavailable("Privacy request list is malformed.")
    safe = []
    for row in result:
        if not isinstance(row, dict) or row.get("request_type") not in {"access", "export", "correction", "deletion"}:
            raise PrivacyGovernanceUnavailable("Privacy request list is malformed.")
        if row.get("status") not in {"submitted", "in_review", "completed", "rejected", "cancelled"}:
            raise PrivacyGovernanceUnavailable("Privacy request status is invalid.")
        safe.append({
            "id": _uuid(row.get("id")),
            "request_type": row["request_type"],
            "status": row["status"],
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "completed_at": row.get("completed_at"),
        })
    return safe


def record_ai_transfer_event(
    settings: Settings, *, user_id: UUID, provider: str, model: str,
    operation: str, outcome: str, consent_event_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> str:
    if not isinstance(user_id, UUID):
        raise ValueError("Verified user UUID is required.")
    if provider != "deepseek" or operation not in {"text", "vision"}:
        raise ValueError("Unsupported AI transfer identity.")
    if outcome not in {"attempted", "succeeded", "failed", "unknown"} or not model or len(model) > 100:
        raise ValueError("AI transfer metadata is invalid.")
    if operation == "vision" and (not isinstance(consent_event_id, UUID) or not isinstance(correlation_id, UUID)):
        raise ValueError("Vision transfer requires consent evidence and a correlation ID.")
    result = _rpc(settings, "record_ai_data_transfer_event", {
        "p_user_id": str(user_id),
        "p_provider": provider,
        "p_model": model,
        "p_operation": operation,
        "p_outcome": outcome,
        "p_consent_event_id": str(consent_event_id) if consent_event_id else None,
        "p_correlation_id": str(correlation_id) if correlation_id else None,
    })
    return _uuid(result)
