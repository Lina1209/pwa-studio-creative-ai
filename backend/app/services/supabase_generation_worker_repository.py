"""Supabase PostgREST adapter for durable generation-job lifecycle RPCs.

The caller owns the AsyncClient lifecycle. This adapter is server-only and must
never be constructed with browser credentials or exposed to an API response.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.services.generation_worker import ClaimedImageJob
from app.services.worker_repository_errors import WorkerRepositoryError


@dataclass(frozen=True)
class GenerationJobInventoryRow:
    job_id: UUID
    status: str
    result_storage_path: str | None
    updated_at: str
    lease_expires_at: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    available_at: str | None = None
    last_error_code: str | None = None




@dataclass(frozen=True)
class ProviderOperationJournal:
    operation_id: UUID
    state: str
    provider_request_id: str | None
    created: bool


@dataclass(frozen=True)
class ProviderCostEventResult:
    event_id: int
    created: bool
    cumulative_known_cost_usd: Decimal
    budget_limit_usd: Decimal | None
    budget_exceeded: bool | None


@dataclass(frozen=True)
class CreditedCompletion:
    completed: bool
    replayed: bool
    available_credits: int | None
    reserved_credits: int | None


class WorkerRepositoryNotConfiguredError(RuntimeError):
    pass


class WorkerRepositoryError(RuntimeError):
    """Sanitized database adapter failure with an explicit retry policy."""

    def __init__(self, error_code: str, *, retryable: bool = True):
        self.error_code = error_code
        self.retryable = retryable
        super().__init__(error_code)


def _repository_error_code(exc: Exception) -> tuple[str, bool]:
    """Classify transport and HTTP failures without exposing response bodies."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(exc, httpx.TimeoutException):
        return "database_request_timeout", True
    if isinstance(exc, httpx.RequestError):
        return "database_connection_error", True
    if isinstance(status, int):
        if status in {408, 425, 429} or status >= 500:
            return "database_temporarily_unavailable", True
        if status in {401, 403}:
            return "database_credentials_rejected", False
        if 400 <= status < 500:
            return "database_request_rejected", False
    return "database_response_unavailable", True


class SupabaseGenerationJobRepository:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        key = settings.supabase_service_role_key
        if not settings.supabase_url or not key:
            raise WorkerRepositoryNotConfiguredError(
                "Server-side generation job database access is not configured."
            )
        self._base_url = settings.supabase_url.rstrip("/")
        self._client = client
        self._headers = {
            "apikey": key,
            "Content-Type": "application/json",
        }
        if key.startswith("eyJ"):
            self._headers["Authorization"] = f"Bearer {key}"

    async def _rpc(self, function: str, payload: dict[str, Any]) -> Any:
        try:
            response = await self._client.post(
                f"{self._base_url}/rest/v1/rpc/{function}",
                json=payload,
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            code, retryable = _repository_error_code(exc)
            raise WorkerRepositoryError(code, retryable=retryable) from exc


    async def begin_provider_operation(
        self, job_id: UUID, worker_id: str, provider: str, idempotency_key: str
    ) -> ProviderOperationJournal:
        data = await self._rpc(
            "begin_generation_provider_operation",
            {
                "p_job_id": str(job_id),
                "p_worker_id": worker_id,
                "p_provider": provider,
                "p_idempotency_key": idempotency_key,
            },
        )
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise WorkerRepositoryError("Provider operation journal returned an invalid response.")
        row = data[0]
        try:
            state = row["operation_state"]
            request_id = row.get("provider_request_id")
            if state not in {"submitting", "accepted", "unknown", "provider_failed", "result_received"}:
                raise ValueError("state")
            if request_id is not None and (not isinstance(request_id, str) or not request_id):
                raise ValueError("provider_request_id")
            if not isinstance(row["created"], bool):
                raise ValueError("created")
            return ProviderOperationJournal(
                UUID(str(row["operation_id"])), state, request_id, row["created"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerRepositoryError("Provider operation journal metadata is invalid.") from exc

    async def mark_provider_operation_accepted(
        self, job_id: UUID, worker_id: str, provider_request_id: str
    ) -> bool:
        return await self._boolean_rpc(
            "mark_generation_provider_operation_accepted",
            {"p_job_id": str(job_id), "p_worker_id": worker_id,
             "p_provider_request_id": provider_request_id},
        )

    async def mark_provider_operation_unknown(
        self, job_id: UUID, worker_id: str, error_code: str
    ) -> bool:
        return await self._boolean_rpc(
            "mark_generation_provider_operation_unknown",
            {"p_job_id": str(job_id), "p_worker_id": worker_id, "p_error_code": error_code},
        )

    async def mark_provider_operation_failed(
        self, job_id: UUID, worker_id: str, error_code: str
    ) -> bool:
        return await self._boolean_rpc(
            "mark_generation_provider_operation_failed",
            {"p_job_id": str(job_id), "p_worker_id": worker_id, "p_error_code": error_code},
        )

    async def mark_provider_operation_result_received(
        self, job_id: UUID, worker_id: str, provider_request_id: str | None = None
    ) -> bool:
        return await self._boolean_rpc(
            "mark_generation_provider_operation_result_received",
            {"p_job_id": str(job_id), "p_worker_id": worker_id,
             "p_provider_request_id": provider_request_id},
        )

    async def get_provider_operation(self, job_id: UUID) -> ProviderOperationJournal | None:
        try:
            response = await self._client.get(
                f"{self._base_url}/rest/v1/generation_provider_operations",
                params={"select": "id,state,provider_request_id", "job_id": f"eq.{job_id}", "limit": "2"},
                headers=self._headers,
            )
            response.raise_for_status()
            rows = response.json()
        except Exception as exc:
            code, retryable = _repository_error_code(exc)
            raise WorkerRepositoryError(code, retryable=retryable) from exc
        if not isinstance(rows, list) or len(rows) > 1:
            raise WorkerRepositoryError("Provider operation journal read returned an invalid response.")
        if not rows:
            return None
        row = rows[0]
        try:
            state = row["state"]
            request_id = row.get("provider_request_id")
            if state not in {"submitting", "accepted", "unknown", "provider_failed", "result_received"}:
                raise ValueError("state")
            if request_id is not None and (not isinstance(request_id, str) or not request_id):
                raise ValueError("provider_request_id")
            return ProviderOperationJournal(UUID(str(row["id"])), state, request_id, False)
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerRepositoryError("Provider operation journal row is invalid.") from exc

    async def list_owner_job_inventory(
        self, owner_id: UUID, *, page_size: int = 500, max_pages: int = 20
    ) -> list[GenerationJobInventoryRow]:
        """Read-only, bounded inventory used by the storage recovery scanner."""
        if not 1 <= page_size <= 1000 or not 1 <= max_pages <= 100:
            raise ValueError("Job inventory pagination is out of bounds.")
        rows_out: list[GenerationJobInventoryRow] = []
        for page in range(max_pages):
            try:
                response = await self._client.get(
                    f"{self._base_url}/rest/v1/generation_jobs",
                    params={
                        "select": "id,status,result_storage_path,updated_at,lease_expires_at,attempt_count,max_attempts,available_at,last_error_code",
                        "user_id": f"eq.{owner_id}",
                        "order": "id.asc",
                        "limit": str(page_size),
                        "offset": str(page * page_size),
                    },
                    headers=self._headers,
                )
                response.raise_for_status()
                rows = response.json()
            except Exception as exc:
                code, retryable = _repository_error_code(exc)
                raise WorkerRepositoryError(code, retryable=retryable) from exc
            if not isinstance(rows, list):
                raise WorkerRepositoryError("Generation job inventory returned an invalid response.")
            for row in rows:
                if not isinstance(row, dict):
                    raise WorkerRepositoryError("Generation job inventory returned an invalid row.")
                try:
                    job_id = UUID(str(row["id"]))
                    status = row["status"]
                    updated_at = row["updated_at"]
                    result_path = row.get("result_storage_path")
                    if status not in {
                        "queued", "running", "retry_wait", "succeeded",
                        "failed", "cancel_requested", "cancelled", "expired",
                    }:
                        raise ValueError("status")
                    if not isinstance(updated_at, str) or not updated_at:
                        raise ValueError("updated_at")
                    if result_path is not None and not isinstance(result_path, str):
                        raise ValueError("result_storage_path")
                    lease_expires_at = row.get("lease_expires_at")
                    available_at = row.get("available_at")
                    last_error_code = row.get("last_error_code")
                    attempt_count = row.get("attempt_count", 0)
                    max_attempts = row.get("max_attempts", 3)
                    if lease_expires_at is not None and not isinstance(lease_expires_at, str):
                        raise ValueError("lease_expires_at")
                    if available_at is not None and not isinstance(available_at, str):
                        raise ValueError("available_at")
                    if last_error_code is not None and not isinstance(last_error_code, str):
                        raise ValueError("last_error_code")
                    if (isinstance(attempt_count, bool) or not isinstance(attempt_count, int)
                            or attempt_count < 0 or isinstance(max_attempts, bool)
                            or not isinstance(max_attempts, int) or max_attempts < 1
                            or attempt_count > max_attempts):
                        raise ValueError("attempt_counters")
                    rows_out.append(GenerationJobInventoryRow(
                        job_id, status, result_path, updated_at, lease_expires_at,
                        attempt_count, max_attempts, available_at, last_error_code
                    ))
                except (KeyError, TypeError, ValueError) as exc:
                    raise WorkerRepositoryError(
                        "Generation job inventory returned incomplete metadata."
                    ) from exc
            if len(rows) < page_size:
                return rows_out
        raise WorkerRepositoryError("Generation job inventory page limit reached.")

    async def claim_next(self, worker_id: str, lease_seconds: int = 180) -> ClaimedImageJob | None:
        data = await self._rpc(
            "claim_next_generation_job",
            {"p_worker_id": worker_id, "p_lease_seconds": lease_seconds},
        )
        if not isinstance(data, list) or len(data) > 1:
            raise WorkerRepositoryError("Generation job claim returned an invalid response.")
        if not data:
            return None
        row = data[0]
        if not isinstance(row, dict):
            raise WorkerRepositoryError("Generation job claim returned an invalid row.")
        try:
            snapshot = row["request_snapshot"]
            if not isinstance(snapshot, dict):
                raise TypeError("request_snapshot")
            return ClaimedImageJob(
                job_id=UUID(str(row["job_id"])),
                user_id=UUID(str(row["user_id"])),
                job_type=str(row["job_type"]),
                provider=str(row["provider"]),
                model=str(row["model"]),
                request_snapshot=snapshot,
                attempt_count=int(row["attempt_count"]),
                max_attempts=int(row["max_attempts"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerRepositoryError(
                "Generation job claim returned incomplete job metadata."
            ) from exc

    async def _boolean_rpc(self, function: str, payload: dict[str, Any]) -> bool:
        data = await self._rpc(function, payload)
        if not isinstance(data, bool):
            raise WorkerRepositoryError("Generation job transition returned an invalid response.")
        return data

    async def heartbeat(self, job_id: UUID, worker_id: str, lease_seconds: int) -> bool:
        return await self._boolean_rpc(
            "heartbeat_generation_job",
            {"p_job_id": str(job_id), "p_worker_id": worker_id, "p_lease_seconds": lease_seconds},
        )

    async def retry(self, job_id: UUID, worker_id: str, error_code: str, delay_seconds: int) -> bool:
        return await self._boolean_rpc(
            "retry_generation_job",
            {
                "p_job_id": str(job_id),
                "p_worker_id": worker_id,
                "p_error_code": error_code,
                "p_retry_delay_seconds": delay_seconds,
            },
        )

    async def fail(self, job_id: UUID, worker_id: str, error_code: str) -> bool:
        return await self._boolean_rpc(
            "fail_generation_job",
            {"p_job_id": str(job_id), "p_worker_id": worker_id, "p_error_code": error_code},
        )



    async def complete_credited(
        self, job_id: UUID, worker_id: str, result_path: str
    ) -> CreditedCompletion:
        """Capture the job's credit hold in the same transaction as completion.

        The worker must first verify the uploaded private object (bucket, owner
        path, MIME, byte count, checksum and content) using the storage adapter.
        """
        data = await self._rpc(
            "complete_credited_generation_job",
            {
                "p_job_id": str(job_id),
                "p_worker_id": worker_id,
                "p_result_storage_path": result_path,
            },
        )
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise WorkerRepositoryError("Credited completion returned an invalid response.")
        row = data[0]
        try:
            completed = row["completed"]
            replayed = row["replayed"]
            available = row.get("available_credits")
            reserved = row.get("reserved_credits")
            if not isinstance(completed, bool) or not isinstance(replayed, bool):
                raise ValueError("completion flags")
            for value in (available, reserved):
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                ):
                    raise ValueError("wallet balance")
            if completed and (available is None or reserved is None):
                raise ValueError("missing wallet balance")
            if replayed and not completed:
                raise ValueError("replay without completion")
            return CreditedCompletion(completed, replayed, available, reserved)
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerRepositoryError(
                "Credited completion returned incomplete or invalid metadata."
            ) from exc

    async def record_provider_cost(
        self,
        *,
        job_id: UUID,
        user_id: UUID,
        operation_key: str,
        provider: str,
        model: str,
        provider_usage_id: str | None,
        cost_usd: Decimal | None,
        cost_source: str,
        input_units: int | None = None,
        output_units: int | None = None,
        total_units: int | None = None,
        unit_kind: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> ProviderCostEventResult:
        """Append provider billing evidence; this never changes customer credits.

        All identity and cost arguments must come from trusted server-side job
        and provider adapter data, never directly from browser request fields.
        """
        if not isinstance(job_id, UUID) or not isinstance(user_id, UUID):
            raise WorkerRepositoryError("Provider cost event identity is invalid.", retryable=False)
        if not isinstance(operation_key, str) or not 8 <= len(operation_key) <= 200:
            raise WorkerRepositoryError("Provider cost operation key is invalid.", retryable=False)
        if cost_source not in {"reported", "estimated", "unknown"}:
            raise WorkerRepositoryError("Provider cost source is invalid.", retryable=False)
        if (cost_source == "unknown") != (cost_usd is None):
            raise WorkerRepositoryError("Provider cost amount and source are inconsistent.", retryable=False)
        if cost_usd is not None:
            if not isinstance(cost_usd, Decimal) or not cost_usd.is_finite() or cost_usd < 0 or cost_usd > Decimal("1000000000"):
                raise WorkerRepositoryError("Provider cost amount is invalid.", retryable=False)
        for value in (input_units, output_units, total_units):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise WorkerRepositoryError("Provider usage units are invalid.", retryable=False)
        if not isinstance(metadata, dict):
            metadata = {} if metadata is None else metadata
        if not isinstance(metadata, dict):
            raise WorkerRepositoryError("Provider cost metadata must be an object.", retryable=False)

        data = await self._rpc(
            "record_generation_provider_cost",
            {
                "p_job_id": str(job_id),
                "p_user_id": str(user_id),
                "p_operation_key": operation_key,
                "p_provider": provider,
                "p_model": model,
                "p_provider_usage_id": provider_usage_id,
                "p_cost_usd": str(cost_usd) if cost_usd is not None else None,
                "p_cost_source": cost_source,
                "p_input_units": input_units,
                "p_output_units": output_units,
                "p_total_units": total_units,
                "p_unit_kind": unit_kind,
                "p_metadata": metadata,
            },
        )
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise WorkerRepositoryError("Provider cost event returned an invalid response.")
        row = data[0]
        try:
            event_id = row["event_id"]
            created = row["created"]
            known_cost = Decimal(str(row["cumulative_known_cost_usd"]))
            budget_raw = row.get("budget_limit_usd")
            budget = Decimal(str(budget_raw)) if budget_raw is not None else None
            exceeded = row.get("budget_exceeded")
            if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
                raise ValueError("event id")
            if not isinstance(created, bool):
                raise ValueError("created")
            if not known_cost.is_finite() or known_cost < 0:
                raise ValueError("known cost")
            if budget is not None and (not budget.is_finite() or budget < 0):
                raise ValueError("budget")
            if exceeded is not None and not isinstance(exceeded, bool):
                raise ValueError("budget exceeded")
            return ProviderCostEventResult(event_id, created, known_cost, budget, exceeded)
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise WorkerRepositoryError(
                "Provider cost event returned incomplete or invalid metadata."
            ) from exc

    async def complete(self, job_id: UUID, worker_id: str, result_path: str) -> bool:
        return await self._boolean_rpc(
            "complete_generation_job",
            {
                "p_job_id": str(job_id),
                "p_worker_id": worker_id,
                "p_result_storage_path": result_path,
            },
        )
