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
- Migration 0014 adds draft claim/ack/lease/recovery RPCs, but this is still not an active queue. No API route, worker, scheduler, retry dispatcher process, or credit ledger is implemented.
- Backend must validate Supabase JWT, derive owner_id from `sub`, validate request and check referenced asset ownership before inserting. Never trust a client owner_id.
- Job insert and outbox insert must occur in one database transaction. The outbox dispatcher must use atomic row claims (`FOR UPDATE SKIP LOCKED` or equivalent), bounded delivery attempts, and claim fencing.
- Every worker state update must match both job id and current lease_token. Stale attempts must not update current job state or publish output.
- Idempotency conflict behavior must be implemented in the API: same owner/key + same fingerprint returns existing job; same owner/key + different fingerprint returns HTTP 409.
- The request_payload schema and retention policy still require a field allowlist; prompts and references may contain personal data. Never put secrets, signed URLs, or raw provider credentials in it.
- Credit reservation/settlement fields are placeholders only. Do not debit users until a separate atomic credit ledger and reconciliation flow is designed and tested.
- Migration is additive but still requires review against the live schema, a backup, and isolated Supabase tests before any manual application. The preflight SQL is read-only; it is not a migration test.
## Draft atomic queue RPCs (migration 0014; not applied)
File: `supabase/migrations/0014_generation_job_queue_rpcs.sql`.

The SQL draft adds backend-only `SECURITY DEFINER` RPCs with a fixed `pg_catalog, public, pg_temp` search path and explicit revokes from `PUBLIC`, `anon`, and `authenticated`:
- `claim_generation_outbox` atomically claims due outbox events with `FOR UPDATE SKIP LOCKED`, a claim token, worker identity, and a bounded delivery lease.
- `ack_generation_outbox` acknowledges only the current claim token. A dispatcher crash leaves the claim leased for later redelivery; after 20 delivery attempts, the next claim sweep marks the event dead-lettered. Stale claims cannot acknowledge a newer claim.
- `claim_generation_job` atomically claims one due job, increments attempts, and issues a fresh fencing token/lease.
- `heartbeat_generation_job`, `complete_generation_job`, and `fail_generation_job` require the current lease token. Retryable failure and retry-outbox insertion occur in one transaction.
- `request_generation_job_cancel` checks both job id and owner id; backend must derive owner id from the verified bearer token. `finish_generation_job_cancel` only completes the active matching lease.
- `recover_expired_generation_jobs` uses row locks with `SKIP LOCKED`; it finishes expired cancellations, retries jobs with attempts remaining, and fails exhausted jobs.

These functions are schema proposals only. No function has been executed or granted in the connected Supabase project. The read-only catalogue check is `supabase/tests/0014_generation_job_rpcs_preflight.sql`.

## Required isolated integration tests before use
- Run concurrent claimers against a seeded queue; assert each job has exactly one live lease token.
- Deliver the same outbox event more than once; assert worker processing remains idempotent and output/charges are not duplicated.
- Expire a lease, reclaim it, then submit completion/failure from the old token; assert the stale operation returns false/stale and changes nothing.
- Race cancellation against completion and retry; assert exactly one terminal state and no late result publication.
- Crash an outbox dispatcher after publish but before ack; verify redelivery is safe. Crash before publish; verify lease expiry permits reclaim.
- Force outbox delivery attempts to the limit; verify explicit dead-letter state and operational alerting.
- Verify anon/authenticated cannot execute any privileged RPC; service_role can execute only from the backend, never from a browser.
- Verify user A cannot cancel user B's job even when a valid job UUID is known.
- Test max attempts, retry delay, invalid parameters, expired lease boundaries, and all table CHECK constraints on a disposable Supabase project.

Operational caution: outbox dispatch is at-least-once, not exactly-once. The worker must be idempotent. The database lease fences state writes, but cannot undo an external provider call that was already accepted; provider-side idempotency and billing reconciliation remain mandatory.
- `complete_generation_job` additionally requires the result `media_assets` row to have the same owner as the job and a non-null storage path; backend must still verify the private object upload succeeded before creating that row.
\n## Static source guardrails\n\n`backend/tests/test_generation_queue_migration_contract.py` checks the draft's fixed SECURITY DEFINER search paths, explicit function grants/revokes, PostgreSQL `LIMIT ... FOR UPDATE SKIP LOCKED` ordering, result-asset owner/storage-path check, fencing predicates, and preflight coverage. These are source-contract tests only; they are not a PostgreSQL parser or substitute for isolated Supabase concurrency tests. They have not yet been executed in CI.\n

## Disposable behavior test (not executed)
- Added `supabase/tests/0015_generation_job_queue_behavior.sql`.
- It is intended for a disposable LOCAL Supabase database only, after migrations 0012, 0013, and 0014 have been applied locally.
- The script creates two temporary Auth users and fixture rows inside a transaction, exercises owner isolation, stale completion, retry/outbox insertion, queued and active cancellation, lease recovery, outbox claim/ack, and dead-lettering, then rolls everything back.
- It is sequential and does not prove concurrent claim behavior. A separate multi-session test is still required for actual race testing.
- The script has NOT been executed. This repository currently has no checked-in Supabase local config or CI workflow visible in the feature branch, so do not infer a runnable local stack from the presence of this SQL file.
- Never run this script or the draft migrations against production.
