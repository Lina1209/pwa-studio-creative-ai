"""Supabase RPC adapter for the AI budget ledger.

This adapter is not wired to API routes. It calls only the private RPC contract
and deliberately avoids logging response bodies, credentials, or user content.
"""
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import Settings
from app.services.ai_budget import (
    AIReservation,
    AIReservationRequest,
)


class AIBudgetStoreUnavailable(RuntimeError):
    """The private budget RPC could not safely confirm an operation."""


class SupabaseAIBudgetStore:
    def __init__(self, settings: Settings, *, timeout_seconds: float = 5.0):
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    def _rpc(self, function_name: str, payload: dict):
        if not self.settings.supabase_url or not self.settings.supabase_service_role_key:
            raise AIBudgetStoreUnavailable("AI budget storage is not configured.")
        url = f"{self.settings.supabase_url.rstrip('/')}/rest/v1/rpc/{function_name}"
        key = self.settings.supabase_service_role_key
        headers = {
            "apikey": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {key}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            # Do not include raw provider/database error bodies or credentials.
            raise AIBudgetStoreUnavailable(
                f"AI budget RPC failed: {function_name}."
            ) from exc

    def reserve(self, request: AIReservationRequest) -> AIReservation:
        rows = self._rpc(
            "reserve_ai_budget",
            {
                "p_request_id": request.request_id,
                "p_user_id": request.user_id,
                "p_idempotency_key": request.idempotency_key,
                "p_request_fingerprint": request.request_fingerprint,
                "p_endpoint": request.endpoint,
                "p_provider": request.provider,
                "p_model": request.model,
                "p_reserved_usd": str(request.reserved_usd),
            },
        )
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise AIBudgetStoreUnavailable("AI budget reserve RPC returned an invalid result.")
        row = rows[0]
        try:
            amount = Decimal(str(row["reserved_usd"]))
            reservation_id = str(row["reservation_id"])
            status = str(row["reservation_status"])
            created = row["reservation_created"] is True
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise AIBudgetStoreUnavailable("AI budget reserve RPC returned an invalid result.") from exc
        if not amount.is_finite() or amount <= 0 or not reservation_id:
            raise AIBudgetStoreUnavailable("AI budget reserve RPC returned an invalid result.")
        return AIReservation(
            reservation_id=reservation_id,
            reserved_usd=amount,
            status=status,
            created=created,
        )

    def settle(self, reservation_id: str, actual_cost_usd: Decimal | None) -> None:
        if actual_cost_usd is None:
            self.mark_unknown(reservation_id, "provider_cost_unknown")
            return
        self._rpc(
            "settle_ai_budget",
            {
                "p_reservation_id": reservation_id,
                "p_actual_usd": str(actual_cost_usd),
            },
        )

    def mark_unknown(self, reservation_id: str, safe_reason: str) -> None:
        self._rpc(
            "mark_ai_budget_unknown",
            {
                "p_reservation_id": reservation_id,
                "p_safe_reason": safe_reason,
            },
        )

    def release_confirmed_no_charge(self, reservation_id: str, safe_reason: str) -> None:
        self._rpc(
            "release_ai_budget_no_charge",
            {
                "p_reservation_id": reservation_id,
                "p_safe_reason": safe_reason,
            },
        )
