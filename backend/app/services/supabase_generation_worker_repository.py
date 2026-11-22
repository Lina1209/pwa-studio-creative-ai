"""Supabase PostgREST adapter for durable generation-job lifecycle RPCs.

The caller owns the AsyncClient lifecycle. This adapter is server-only and must
never be constructed with browser credentials or exposed to an API response.
"""
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.services.generation_worker import ClaimedImageJob


@dataclass(frozen=True)
class GenerationJobInventoryRow:
    job_id: UUID
    status: str
    result_storage_path: str | None
    updated_at: str


class WorkerRepositoryNotConfiguredError(RuntimeError):
    pass


class WorkerRepositoryError(RuntimeError):
    pass


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
            status = getattr(getattr(exc, "response", None), "status_code", "unavailable")
            raise WorkerRepositoryError(
                f"Generation worker database operation failed (HTTP {status})."
            ) from exc

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
                        "select": "id,status,result_storage_path,updated_at",
                        "user_id": f"eq.{owner_id}",
                        "order": "updated_at.asc,id.asc",
                        "limit": str(page_size),
                        "offset": str(page * page_size),
                    },
                    headers=self._headers,
                )
                response.raise_for_status()
                rows = response.json()
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", "unavailable")
                raise WorkerRepositoryError(
                    f"Generation job inventory failed (HTTP {status})."
                ) from exc
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
                    rows_out.append(
                        GenerationJobInventoryRow(job_id, status, result_path, updated_at)
                    )
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

    async def complete(self, job_id: UUID, worker_id: str, result_path: str) -> bool:
        return await self._boolean_rpc(
            "complete_generation_job",
            {
                "p_job_id": str(job_id),
                "p_worker_id": worker_id,
                "p_result_storage_path": result_path,
            },
        )
