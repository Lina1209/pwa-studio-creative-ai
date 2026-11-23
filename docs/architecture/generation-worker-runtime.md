# Generation worker runtime

Status: runner loop implemented; production runtime intentionally not enabled.

## Responsibilities

- Run as a separate process, never inside the FastAPI request lifecycle.
- Claim one durable job at a time through `claim_next_generation_job_v2`.
- Process the claimed job through the existing `GenerationWorker` contract.
- Poll an empty queue using a short idle delay.
- Back off after database/claim errors without exposing response bodies or secrets.
- Propagate process shutdown cancellation. Database leases and the provider journal remain the source of truth for recovery.

## Safety boundary

The runner accepts an already constructed repository and worker. It does not create service-role credentials, provider clients, or storage clients. It does not register a fake provider and does not make provider requests.

The runtime must remain disabled until all of the following are separately reviewed and tested:

1. A real image provider adapter is selected and its idempotency and lookup guarantees are documented.
2. A private Supabase Storage adapter verifies object metadata and ownership.
3. A dedicated worker entrypoint constructs the approved adapters from server-only secrets.
4. The deployment host runs a separate worker process with bounded concurrency and health monitoring.
5. The provider and storage spending limits are reviewed.

DeepSeek remains the only configured text AI provider. This runner does not reinterpret DeepSeek chat as image generation and does not introduce another AI provider.

## Configuration

Existing runtime flags remain fail-closed:
- `GENERATION_JOBS_ENABLED=false`
- `GENERATION_JOB_WORKER_READY=false`
- `GENERATION_WORKER_RUNTIME_ENABLED=false`

No production environment variables were changed and no deployment was performed.
