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


## Private image result storage and retrieval

`SupabasePrivateImageStorage` is a server-only adapter using the Supabase Storage REST API. It:
- requires the server-side service key and never exposes it to the browser;
- uses deterministic owner/job paths and create-only uploads (`x-upsert=false`);
- verifies that the configured bucket is private before accepting an object;
- checks the owner-scoped object listing, MIME type, bounded file size, and downloads the stored bytes through the authenticated endpoint;
- compares the stored bytes with the provider result and calculates SHA-256;
- preserves objects on transient verification errors so a retry can safely reconcile them, and removes only newly created objects after definitive verification failures.

The authenticated `GET /api/jobs/{job_id}/result` route first loads the result locator with both the job ID and verified user ID. Only `succeeded` jobs with a valid storage path and SHA-256 can receive a signed URL. Before signing, the adapter re-verifies the owner/job path and the full stored object checksum. Signed URLs expire after 60 seconds and the API response is marked `private, no-store`.

Supabase private bucket downloads and signed URL behavior follow the official Storage documentation: [private downloads](https://supabase.com/docs/guides/storage/serving/downloads) and [create signed URL](https://supabase.com/docs/reference/python/storage-from-createsignedurl).

The worker runtime remains disabled. No real provider is registered and no storage credentials or production settings were changed.
