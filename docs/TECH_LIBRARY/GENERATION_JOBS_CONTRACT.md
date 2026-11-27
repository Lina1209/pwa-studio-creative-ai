# Generation Jobs — API and worker contract

Status: design + inactive pure-Python lifecycle helper. No endpoint, database table, queue, worker, provider integration, or billable call is enabled.

## Why jobs instead of a synchronous generation request

Image/video generation can outlive an HTTP request and needs cancellation, retry limits, worker recovery, and durable status. FastAPI's own guidance distinguishes small in-process background work from heavier computation that may need a separate worker/queue. Therefore do not use `BackgroundTasks` or an in-memory task list as the durable generation system. See the official [FastAPI Background Tasks guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/).

## Proposed lifecycle

`queued → processing → succeeded`

`processing → retry_wait → processing` (bounded retry)

`queued/retry_wait → cancelled`

`processing → cancel_requested → cancelled`

Any active job whose worker lease expires is recovered by a scheduler:
- ordinary processing job: retry_wait if attempts remain, otherwise failed;
- cancel_requested job: cancelled; discard any late result.

Terminal states: `succeeded`, `failed`, `cancelled`.

## Inactive reference implementation

- `backend/app/services/generation_job_lifecycle.py` defines immutable job state and transition helpers.
- `backend/tests/test_generation_job_lifecycle.py` covers state transitions, retries, lease expiry, cancellation, and validation.
- This module is not imported by the API and does not persist state or execute work. A database repository must implement the same transitions atomically before any endpoint can use it.

## Proposed API surface (not implemented)

- `POST /api/generation/jobs` → 202 Accepted; returns job id and status URL only after the job and its dispatch/outbox record are durably committed.
- `GET /api/generation/jobs/{job_id}` → owner-scoped status and safe progress.
- `POST /api/generation/jobs/{job_id}/cancel` → cooperative cancellation request.
- `GET /api/generation/jobs/{job_id}/result` → owner-scoped short-lived URL only after success.

The server derives owner identity from the verified Supabase bearer token. Never accept owner_id, provider credentials, arbitrary storage paths, or provider callback URLs from the client. Every read, cancel, and result lookup checks ownership.

## Durable persistence and dispatch requirements

Before endpoint implementation:
1. Add a private generation_jobs table with UUID primary key, owner_id FK, idempotency_key, request_fingerprint, status, attempt_count, max_attempts, lease_expires_at, next_attempt_at, safe_error_code, result_asset_id, created_at, updated_at, completed_at.
2. Unique constraint on `(owner_id, idempotency_key)`. Same key + same canonical request returns the existing job; same key + different request fingerprint returns 409. Idempotency is scoped per owner.
3. Add a transactional outbox or database-backed claim mechanism so a committed job cannot be lost between database commit and queue publication.
4. Worker claims use atomic conditional updates/row locking. Never rely on process-local locks for multi-worker correctness.
5. Lease heartbeat and stale-lease recovery must be idempotent. A stale worker must not overwrite a newer attempt's state.
6. All state changes use expected-state/attempt predicates; terminal states cannot be reopened by late callbacks.
7. Persist only safe provider error codes, not raw prompts, credentials, provider responses, or stack traces in user-visible job records.

## Worker and retry rules

- Separate worker process and bounded concurrency; do not run expensive image/video generation inside the FastAPI web worker.
- Retry only transient errors (timeouts, rate limits, temporary provider failures), with exponential backoff + jitter and a strict maximum attempt count.
- Do not retry policy rejections, invalid inputs, ownership failures, insufficient balance, or permanent provider errors.
- Provider idempotency support should be used when available; otherwise document the duplicate-billing window and reconcile provider request IDs.
- Cancellation is cooperative. If provider cancellation is unavailable, stop waiting, prevent result publication, and clean up any orphaned private object.
- A job is not considered succeeded until the private output asset is stored and ownership metadata is committed.

## Billing, consent, and data safety

- Before acceptance, show the selected provider/model, estimated cost or credit charge, input/reference count, retention, and user confirmation.
- Reserve credits atomically before dispatch; settle against actual usage after completion; release reservations on terminal failure/cancellation. Repeated requests must not double-charge.
- DeepSeek remains the current text provider. No image provider is selected by this contract.
- Validate reference ownership before reading bytes; then validate signatures/MIME, safely decode, enforce dimensions/pixel count and decompression-bomb limits, and scan as appropriate.
- Store outputs in a private bucket with owner-scoped paths and short-lived signed URLs. No public bucket.
- Do not send character/reference image bytes to a provider until the user confirms the provider and request. Never include unrelated library assets.
- Provide deletion/retention rules for source references, outputs, failed temporary objects, and provider-side retention disclosures.

## Go-live gates

- [ ] Provider and model explicitly selected and approved; pricing/cost ceiling known.
- [ ] Migration reviewed and applied only after backup + isolated-environment test.
- [ ] RLS and API ownership tests for users A and B, including cross-user job/result/cancel attempts.
- [ ] Idempotency race test with parallel duplicate requests.
- [ ] Worker crash, duplicate delivery, expired lease, late callback, retry, and cancellation tests.
- [ ] Atomic credit reservation/settlement and no-double-charge tests.
- [ ] File decode/pixel/dimension limits and private storage tests.
- [ ] Logs redact secrets and prompts; safe metrics and alerts are available.
- [ ] User-facing consent and clear progress/error/cancel UI.
- [ ] Explicit approval before production deployment or any paid provider request.

## Draft Supabase persistence (migration 0013; not applied)
Files:
- `supabase/migrations/0013_generation_jobs_and_outbox.sql`
- `supabase/tests/0013_generation_jobs_preflight.sql`

The migration draft defines:
- `generation_jobs`: owner, per-owner idempotency key + canonical request fingerprint, type, status, minimal request payload, bounded attempts, worker lease + fencing token, cancellation timestamp, safe error code, result asset reference, estimated/actual cost fields, reserved-credit field, and lifecycle timestamps.
- `generation_job_outbox`: backend-only dispatch records created in the same transaction as a job, with claim/delivery metadata.
- RLS on both tables. Authenticated users can SELECT only their own job rows. Browser roles cannot INSERT/UPDATE/DELETE jobs and have no access to the outbox. Backend service_role is granted server-side CRUD only.
- Indexes for owner history, due jobs, expired leases, and pending outbox records.

Important limitations / review notes:
- This is a schema draft, not a working queue. No claim/ack RPC, worker, scheduler, retry dispatcher, API route, or credit ledger is implemented.
- Backend must validate Supabase JWT, derive owner_id from `sub`, validate request and check referenced asset ownership before inserting. Never trust a client owner_id.
- Job insert and outbox insert must occur in one database transaction. The outbox dispatcher must use atomic row claims (`FOR UPDATE SKIP LOCKED` or equivalent), bounded delivery attempts, and claim fencing.
- Every worker state update must match both job id and current lease_token. Stale attempts must not update current job state or publish output.
- Idempotency conflict behavior must be implemented in the API: same owner/key + same fingerprint returns existing job; same owner/key + different fingerprint returns HTTP 409.
- The request_payload schema and retention policy still require a field allowlist; prompts and references may contain personal data. Never put secrets, signed URLs, or raw provider credentials in it.
- Credit reservation/settlement fields are placeholders only. Do not debit users until a separate atomic credit ledger and reconciliation flow is designed and tested.
- Migration is additive but still requires review against the live schema, a backup, and isolated Supabase tests before any manual application. The preflight SQL is read-only; it is not a migration test.