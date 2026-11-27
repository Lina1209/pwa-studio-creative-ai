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

### Local test-runner blockers discovered during review
- The feature branch does not contain `supabase/config.toml`, so the Supabase CLI local stack is not configured in-repository.
- Two historical migration files share the same numeric version prefix: `0005_cloud_projects_and_storage.sql` and `0005_moderation_admin.sql`. A CLI migration runner that treats the prefix as the migration version may reject this history as duplicated.
- These historical files were deliberately not renamed or reordered: doing so without knowing the connected project's applied migration history could create drift or re-apply risk.
- Before a local `supabase db reset` can be used as a trustworthy validation path, the migration history needs a reviewed, non-destructive versioning plan and a local config. Until then, the SQL behavior harness is prepared but not runnable through the repository's standard Supabase CLI workflow.


## Two-session concurrency test plan (manual, disposable database only)

The sequential SQL harness above cannot prove row-lock behavior. Once a disposable local Supabase database is available and migrations 0012–0014 have been applied there, run the following with two independent SQL sessions. Use a single dedicated queued job (and move all other queued/retry jobs' `next_attempt_at` into the future) so the result is unambiguous.

### Job claim race
1. In Session A, start a transaction and claim the one due job:
   `begin;`
   `select id, status, lease_token from public.claim_generation_job('race-worker-A', 120);`
   `select pg_sleep(10);`
   Keep Session A open during the sleep.
2. During that sleep, in Session B run:
   `select id, status, lease_token from public.claim_generation_job('race-worker-B', 120);`
3. Expected: Session A returns the job; Session B returns zero rows because `SKIP LOCKED` skips the locked candidate. Commit Session A.
4. Verify the job has one incremented attempt, `status='processing'`, and exactly the lease token returned to A. A second claim must not return the same processing job.

### Outbox claim race
1. Prepare exactly one due, undelivered outbox row in the disposable database.
2. In Session A:
   `begin;`
   `select * from public.claim_generation_outbox('race-dispatcher-A', 10, 60);`
   `select pg_sleep(10);`
3. During the sleep, Session B runs:
   `select * from public.claim_generation_outbox('race-dispatcher-B', 10, 60);`
4. Expected: A receives the row and B receives no copy of that row. Commit A; then acknowledge using A's returned claim token.
5. Verify the row is delivered once and cannot be acknowledged again with the consumed token.

Record database version, migration hashes, fixture IDs, both session outputs, and final row state. Do not use production data. This is a test procedure, not evidence that concurrency has already passed.

## External provider acceptance, crash windows, and reconciliation (design-only)

The queue and database cannot create exactly-once execution across an external provider boundary. A timeout is not proof that the provider did not accept the request. The worker MUST NOT blindly retry an attempt whose submission outcome is unknown.

### Per-attempt record

A future implementation should persist a separate generation_job_attempts record for each provider attempt, with:
- internal attempt UUID, job ID, monotonically increasing attempt number, and unique internal idempotency key;
- provider and model identifiers from server-side configuration;
- state: prepared, submitting, accepted, completed, failed, unknown, reconciling, or reconciled;
- provider request/operation ID when returned; never store API secrets;
- submitted/accepted/completed timestamps, last checked timestamp, and bounded next reconciliation time;
- safe error category, provider usage/cost evidence, and result asset ID if committed;
- a canonical request fingerprint; do not duplicate raw prompts or reference bytes in attempt logs.

Unique constraints should prevent duplicate internal attempt numbers and duplicate attempt idempotency keys per job. Keep provider identifiers scoped by provider/account where necessary.

### Safe submission protocol

1. Create and commit the attempt row in prepared before making the network call.
2. Change it to submitting with a compare-and-set predicate before sending.
3. Send a stable provider idempotency key if the provider explicitly supports one. Use the same key only when retrying the exact same provider operation; a new logical attempt gets a new key.
4. If the provider returns an acceptance response, persist its operation/request ID and accepted state immediately.
5. If the call times out or the connection drops after submission may have begun, mark the attempt unknown; do not assume failure and do not immediately issue another billable call.
6. If the process crashes while state is submitting, a recovery sweep treats it as ambiguous and moves it to unknown after a conservative timeout. It must not reset it directly to prepared.

Provider idempotency is provider-specific and must be verified against current official documentation and actual endpoint behavior before relying on it. If unsupported, the system must disclose and control the residual duplicate-cost risk.

### Reconciliation state machine

- unknown → reconciling: a reconciler claims the attempt with a bounded lease and fencing token.
- reconciling → accepted/completed/failed: provider status or billing evidence conclusively identifies the operation.
- reconciling → unknown: evidence remains inconclusive; schedule another bounded check and alert after the configured age/attempt threshold.
- A new provider submission is permitted only after evidence establishes that the prior attempt was not accepted, or after an explicit product policy authorizes a carefully controlled duplicate-risk path.
- Provider status callbacks/webhooks must be authenticated, signature-checked, replay-protected, and matched to the stored provider request ID and expected account/model. A callback cannot reopen a terminal internal job or override a newer attempt.

### Crash-window handling

| Crash point | Required recovery |
|---|---|
| Before attempt row commit | No provider call is allowed; job/outbox transaction can be retried idempotently. |
| After prepared, before submission | A worker may safely claim the prepared attempt using a lease and compare-and-set. |
| During submission / after bytes may have left the process | Mark unknown; reconcile before any retry. |
| Provider accepted, response lost | Query provider by idempotency key or operation lookup if supported; otherwise reconcile billing/support evidence and keep state ambiguous. |
| Acceptance persisted, before result polling | Resume polling the same provider operation ID; do not submit a second operation. |
| Result received, before private upload | Re-fetch/poll the same operation where possible; upload idempotently to a deterministic owner/job/attempt object key. |
| Upload succeeded, DB completion failed | Verify the private object and media row, then retry only the fenced DB completion; do not regenerate. |
| DB completion succeeded, acknowledgement lost | Read terminal job/attempt state; duplicate completion/ack must be a no-op. |

### Billing and user-credit coordination

- Store provider cost evidence per attempt separately from the user-facing job charge.
- A provider retry may incur a second provider cost even though the user-facing reservation is still one job reservation. Apply only the approved retry policy; do not silently pass duplicate provider costs to the user.
- The credit ledger contract governs one reservation and one terminal settlement/release per job. Reconciliation may add auditable provider-cost corrections, but must not create a second user debit.
- Unknown provider state means the reservation remains held until a defined timeout/escalation policy resolves it. Do not release credits while an accepted billable operation may still be running.
- A manual resolution must record actor, reason, evidence reference, and compensating ledger operation; never edit or delete historical ledger rows.

### Operational controls and required tests

- Alert on unknown attempts older than the configured service-level threshold, repeated provider lookup failures, cost mismatches, and accepted attempts without a linked job result.
- Bound reconciliation concurrency, polling frequency, provider API spend, and maximum ambiguity age. Use backoff and jitter.
- Redact prompts, reference URLs, signed URLs, tokens, and provider secrets from logs and metrics.
- Test process termination at every crash point in the table, duplicate webhooks, stale reconciliation leases, provider idempotency behavior, provider lookup unavailable, delayed billing records, and repeated result-upload/completion.
- Use a fake provider in automated tests. Any live-provider contract test requires separate explicit approval, a dedicated low-limit test account, and a known spend ceiling.

This section is architecture guidance only. No attempt table, reconciler, provider adapter, webhook, scheduler, or billing behavior is implemented or active.

## Critical review finding: lease expiry is not proof of provider non-acceptance

Status: blocking condition for activation of migration 0014 recovery.

The current draft RPC `recover_expired_generation_jobs` moves every expired `processing` job to `retry_wait` (while attempts remain), then inserts a retry outbox event. That behavior is safe only while a worker lease represents work that has not crossed an external side-effect boundary. Once a provider request may have been submitted, lease expiry alone cannot establish that the provider rejected or never received it.

This creates a concrete duplicate-cost risk: a worker can submit a billable request, lose its process or database connection, and let its lease expire; the recovery RPC can then schedule another provider submission while the first operation is still running or accepted. The later per-attempt reconciliation design above does not currently gate this RPC because the attempt table and reconciler do not exist yet.

Required resolution before any activation:
1. Keep migration 0014 and its recovery RPC inactive until the per-provider-attempt record and reconciliation gate are implemented and tested; OR split the worker lifecycle into a pre-submission phase that can safely expire/requeue and a submitted/unknown phase that is held for reconciliation.
2. Recovery must inspect durable attempt state under the same transaction/locking discipline. It may requeue only when there is conclusive evidence that no provider submission began, or that the provider definitively did not accept the operation.
3. If an attempt is `submitting`, `accepted`, or `unknown`, recovery must retain the job/reservation and schedule reconciliation, never a new provider submission.
4. Add a regression test: provider accepts the request, worker crashes before persisting acceptance, lease expires, and recovery must not create a second provider dispatch.
5. Add a second test for a crash before the network call, proving that a safely unsubmitted attempt can be resumed without duplicate provider cost.

Until these conditions are met, the current queue SQL is a design draft only and must not be enabled with a real provider. The existing no-blind-retry rule takes precedence over automatic lease recovery.


## Additional blocking review: cancellation and outbox delivery semantics

Status: design review finding; migration 0014 remains inactive.

### Cancellation is a request, not proof that provider work stopped

The draft RPC `recover_expired_generation_jobs` currently changes an expired `cancel_requested` job directly to `cancelled`. That is not safe when a provider operation may already have been accepted. A worker lease expiring does not prove that remote work stopped, that cancellation was accepted, or that no billable usage accrued. The current `finish_generation_job_cancel` also does not check lease expiry, so its fencing contract should be tightened before use.

Required behavior before activation:
- Keep cancellation as a durable request while the provider outcome is unresolved.
- Mark the job `cancelled` only after provider cancellation is confirmed, or after a documented terminal outcome is reconciled and the result is safely suppressed. Record any billable usage/cost evidence even when the user does not receive an output.
- If provider cancellation is unsupported or inconclusive, move to/retain an explicit reconciliation-needed state; do not equate local worker shutdown with remote cancellation.
- Define and test the race between provider completion, cancellation request, lease expiry, and result upload. Exactly one internal terminal outcome may win, but late provider billing evidence must still be recorded as an auditable cost correction.
- Require current fencing token and a valid lease (or a separately designed reconciliation lease) for cancellation completion; stale workers must not finalize a newer operation.

### Retry classification must distinguish definite failure from ambiguous timeout

The draft `fail_generation_job(..., p_retryable => true)` can schedule a retry and outbox event. The worker contract must prohibit setting this flag for a timeout, connection reset, or process interruption if the request may have reached the provider. Those outcomes are `unknown`, not safely retryable. Only a provider rejection or other evidence that conclusively establishes non-acceptance may enter ordinary retry scheduling. Provider-specific semantics must be verified rather than inferred from generic HTTP error classes.

### Outbox acknowledgement is at-least-once

The dispatcher can publish an event to an external queue and crash before `ack_generation_outbox`; after the lease expires the same event can be published again. This is expected at-least-once behavior, not a defect that an acknowledgement token alone can eliminate.

Before activation:
- Give each outbox event a stable event identity and make downstream dispatch/consumption idempotent on that identity (and job/attempt identity where appropriate).
- Document whether acknowledgement means accepted by the durable queue, not merely attempted over the network.
- Test crash after successful publish but before DB acknowledgement, duplicate delivery, stale claim acknowledgement, and dead-letter alert/replay procedures.
- Dead-lettering must alert an operator and have an auditable replay path; silently stranded generation jobs are unacceptable.

These findings are review requirements, not implementation claims. No SQL was applied and no worker/provider behavior is active.


## Review finding: current retry interfaces are too permissive

The provider-outcome rule above exposed a mismatch in the draft implementation: the pure-Python lifecycle helper previously treated `retryable=True` as sufficient to retry a `provider_timeout`, while the SQL RPC accepts only a boolean `p_retryable`. Neither interface alone records evidence that the external provider definitely did not accept the request.

The inactive Python helper has now been tightened to require an explicit `ProviderSubmissionOutcome` for a retry. Its default is `unknown`; only `definitely_not_submitted` and `definitely_rejected` permit a retry. A generic timeout with an unknown provider outcome is not retryable.

The SQL migration draft 0014 remains a blocking item: before it can be activated, its failure/recovery contract must carry the same provider-outcome evidence and preserve an explicit reconciliation-needed state for `accepted`/`unknown` attempts. The current `p_retryable boolean` must not be trusted as sufficient evidence. Do not wire the helper or SQL into a worker until both layers agree and regression tests pass.


The inactive pure-Python helper now models `reconciliation_required` explicitly. A timeout or expired lease with `unknown`/ `accepted` provider outcome enters reconciliation rather than retry or cancellation. A retry after lease expiry requires explicit evidence of `definitely_not_submitted` or `definitely_rejected`; an expired cancellation with an unresolved provider outcome also remains in reconciliation. This helper change does not resolve the SQL migration mismatch: the SQL state constraint/RPCs still need a matching reconciliation state and must remain inactive.


## State and persistence compatibility blocker (review update)

The inactive provider-neutral Python lifecycle helper now includes `reconciliation_required`. It enters that state when a provider outcome is `unknown` or `accepted` after a timeout, worker lease expiry, or cancellation race. It permits ordinary retry only when there is conclusive evidence of `definitely_not_submitted` or `definitely_rejected`. A provider completion observed after cancellation suppresses publication but still requires usage/cost reconciliation.

The current SQL draft does NOT yet match this behavior:
- Migration 0013's status CHECK constraint does not include `reconciliation_required`.
- Migration 0014's `fail_generation_job` accepts only a boolean `p_retryable`, with no provider-submission outcome evidence or reconciliation transition.
- `recover_expired_generation_jobs` automatically retries expired processing jobs and marks expired cancellations as cancelled.
- `finish_generation_job_cancel` can mark a cancellation terminal without proving the provider stopped or accounting for billable usage.
- No per-attempt persistence table or reconciliation RPC/worker is implemented.

This is a deliberate activation blocker. Do not patch/apply these SQL drafts piecemeal: first design a coherent additive per-attempt schema, reconciliation state transitions, fencing/lease rules, cancellation confirmation semantics, and credit-hold behavior; then validate the complete migration set on a disposable database with concurrency and crash-window tests. No production migration was run.


## Unified provider attempt/reconciliation design

The consolidated design for per-attempt persistence, provider submission evidence, reconciliation leases, cancellation races, audit events, and credit holds is documented in `docs/TECH_LIBRARY/GENERATION_PROVIDER_RECONCILIATION_CONTRACT.md`. Treat that document as the design authority when revising future SQL drafts. It is not implemented or activated.

Lifecycle helper review note: a user may request cancellation while a job is already in `reconciliation_required`. The helper now records the cancellation timestamp while preserving the reconciliation hold; it does not mark the job cancelled, release credits, or authorize another provider submission. This prevents cancellation from being blocked while preserving the fact that the provider outcome is unresolved.
