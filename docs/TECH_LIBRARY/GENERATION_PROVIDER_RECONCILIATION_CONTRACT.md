# Generation Provider Attempts & Reconciliation Contract

**Status: design only — not implemented or activated.**  
This contract aligns the future SQL queue, provider-neutral worker lifecycle, and credit ledger. It does not select a provider, enable generation, debit credits, or authorize a migration.

## 1. Core invariants

1. A database lease expiring says only that a worker stopped renewing its lease. It does not prove that an external provider did not receive or accept the request.
2. A timeout, connection reset after submission may have begun, process crash, lost acceptance response, or cancellation request is an **ambiguous outcome** unless independent evidence proves otherwise.
3. Ambiguous attempts enter `reconciliation_required`; they are never automatically resubmitted or financially released.
4. Only conclusive evidence of `definitely_not_submitted` or `definitely_rejected` permits the normal retry policy.
5. Provider acceptance/completion after a user's cancellation suppresses publication, but does not erase provider usage or cost.
6. `reconciliation_required` is a durable hold/non-dispatch state, not a success/failure/cancellation terminal state. It must not be claimable by normal workers.
7. All transitions are fenced by job ID, attempt ID, expected state, attempt number, and current lease/reconciliation token. Stale workers and stale reconcilers cannot overwrite newer evidence.
8. User billing is a separate append-only ledger. Provider cost and user credit charge are distinct values.

## 2. Proposed per-attempt persistence

Add an additive `generation_job_attempts` table in a future migration, not in the current draft migrations.

Suggested columns:
- `id uuid primary key`, `job_id uuid not null`, `attempt_number integer not null`;
- `provider_key text not null`, `model_key text not null` (server-selected identifiers only);
- `submission_state text not null`: `prepared`, `submitting`, `accepted`, `completed`, `rejected`, `unknown`, `reconciling`, `reconciled`;
- `submission_outcome text`: `definitely_not_submitted`, `definitely_rejected`, `accepted`, `unknown`;
- `internal_idempotency_key text not null`, `provider_operation_id text null`;
- `request_fingerprint text not null`; never copy raw prompt, reference bytes, signed URLs, or credentials into attempt history;
- `lease_token uuid`, `lease_expires_at timestamptz` for worker fencing; separate reconciliation lease/token fields;
- `submitted_at`, `accepted_at`, `completed_at`, `last_checked_at`, `next_check_at` timestamps;
- `provider_usage jsonb` restricted to a validated allowlist of numeric usage fields; `provider_cost_usd numeric` nonnegative and nullable until verified;
- `safe_error_code text`, `result_asset_id uuid` nullable, `created_at`, `updated_at`.

Constraints/indexes:
- unique `(job_id, attempt_number)`;
- unique `(provider_key, internal_idempotency_key)`;
- unique provider operation identity within the provider/account scope where supported;
- nonnegative verified cost; state/outcome allowlists; indexes for unknown attempts due for reconciliation and job history;
- foreign key to `generation_jobs`; deletion/retention policy must preserve financial/audit evidence as legally required.
- Provider account identity must be a non-secret server-side identifier. Never store API keys.

A separate append-only `generation_job_reconciliation_events` audit table should record attempt ID, prior/new state, evidence category, evidence reference/hash, checked timestamp, actor type/ID, decision, and safe reason code. It must not store raw provider payloads or secrets.

## 3. Submission protocol

1. In one DB transaction, create the attempt as `prepared` and persist its stable internal idempotency key.
2. A fenced compare-and-set moves `prepared -> submitting` before network submission.
3. Send the stable provider idempotency key only if that provider endpoint's current official contract supports it. Reuse it only for the exact same provider operation.
4. On an explicit acceptance response, persist provider operation ID and `accepted` immediately.
5. On a conclusive pre-send failure, record `definitely_not_submitted`. On a definitive provider rejection, record `definitely_rejected`.
6. On timeout, lost connection after send may have begun, or crash while `submitting`, record/derive `unknown`; do not make a new billable call.
7. If the worker crashes before it can write the outcome, a recovery sweep may move stale `submitting` to `unknown`, never back to `prepared`.

Provider idempotency guarantees must be verified separately for the selected provider and exact endpoint before implementation. This design assumes no exactly-once guarantee.

## 4. Reconciliation protocol

- A dedicated backend reconciler claims due `unknown` attempts with an atomic lease and fencing token. Only one current reconciler may own an attempt.
- Query provider operation status and billing/usage evidence where available. Verify provider account, operation identity, request fingerprint, and terminal evidence.
- Provider says accepted/running: retain the hold; schedule bounded backoff and check again.
- Provider confirms completed: persist verified usage/cost; if the user cancelled, suppress result publication but still account for cost. If not cancelled, normal result validation/private upload/ownership commit is still required before job success.
- Provider confirms terminal rejection or proves no request was received: mark reconciled with conclusive evidence; only then may the job follow retry/failure policy and any credit reservation be released or reused under the approved policy.
- Provider cannot establish outcome: remain in reconciliation hold, show a neutral pending status, retry checks within configured bounds, then raise an operational alert/manual review. Do not infer zero usage.
- Manual resolution requires an authorized actor, reason, evidence reference, and immutable audit event. No silent admin override.
- Webhooks, if later supported, require signature verification, timestamp/replay protection, provider/account scoping, and idempotent event processing. A webhook is evidence to reconcile, not permission to bypass fencing.

## 5. Job state transitions

| Current job state | Evidence/event | Next job state | Dispatch? | Credit action |
|---|---|---|---|---|
| processing | definitely not submitted; retry allowed | retry_wait | yes, after backoff | keep one reservation |
| processing | definitely rejected; retry allowed | retry_wait | yes, after backoff | keep one reservation |
| processing | unknown / acceptance response lost | reconciliation_required | no | hold reservation |
| processing | accepted / still running | processing or reconciliation_required after worker loss | no duplicate submit | hold reservation |
| cancel_requested | provider still running / unknown | reconciliation_required | no | hold reservation |
| cancel_requested | provider completed | reconciliation_required until usage/result decision recorded | no publication | account verified provider cost |
| reconciliation_required | verified provider completed | succeeded only if publication allowed and asset safely committed; otherwise failed/cancelled-with-cost according to approved policy | no resubmit | settle verified policy |
| reconciliation_required | verified not accepted / zero billable usage | retry_wait or failed (policy/attempt cap) | only if retry allowed | reservation may be reused/released |
| reconciliation_required | evidence unavailable | reconciliation_required | no | continue hold + alert |

The exact user-visible terminal outcome when a provider completes after cancellation, and the treatment of any cancellation fee, require explicit product/legal approval. Do not silently label such a job as a free cancellation.

## 6. Required RPC surface (future SQL design)

Replace the current boolean-only failure contract with typed, evidence-bearing transitions. Candidate backend-only RPCs:
- `prepare_generation_job_attempt(job_id, lease_token, provider_key, model_key, internal_idempotency_key, request_fingerprint)`;
- `mark_generation_attempt_submitting(attempt_id, attempt_lease_token)`;
- `record_generation_attempt_outcome(attempt_id, attempt_lease_token, outcome, provider_operation_id, safe_error_code)`;
- `claim_generation_reconciliation(batch_size, lease_seconds)`;
- `record_generation_reconciliation(attempt_id, reconciliation_token, evidence_category, provider_state, verified_usage, verified_cost, evidence_reference)`;
- `resolve_generation_reconciliation(attempt_id, reconciliation_token, resolution, reason_code)`.

Every RPC must validate parameters, lock/update rows atomically, enforce expected prior state and current fencing token, and return an explicit stale/no-op result. SECURITY DEFINER functions require fixed search_path, explicit revoke from PUBLIC/anon/authenticated, and service_role-only execute. The browser never calls these functions directly.

These names are design suggestions, not implemented signatures. Do not add isolated RPCs until the entire schema and transition matrix are reviewed together.

## 7. Credit ledger coordination

- Create one reservation per logical job, not per provider retry attempt.
- A retry must not create a second user reservation.
- Keep the reservation held while any attempt is `submitting`, `accepted`, `unknown`, or `reconciling`.
- Release only when evidence establishes no provider acceptance/billable usage, or a verified terminal zero-usage failure.
- Settle from verified provider usage and an approved user-facing pricing policy; never derive the user's charge directly from untrusted client values.
- Provider cost remains per attempt; user charge remains per logical job. Record any approved overage/adjustment as a separate immutable ledger operation.
- Unique idempotency keys and row locks must make reserve/settle/release mutually exclusive and replay-safe.

No credit wallet, ledger, reservation, pricing, or settlement code is implemented by this contract.

## 8. Mandatory isolated tests before activation

1. Crash before attempt creation; crash after prepared; crash after submitting but before network; provider accepted but response lost; crash after operation ID persistence.
2. Expired worker lease while provider may still be running: no automatic retry.
3. Duplicate reconciler claim; expired reconciliation lease; stale reconciler write after a newer claim.
4. Provider reports running, completed, rejected, not-found, and unavailable; ensure not-found is not treated as non-submission unless provider semantics prove it.
5. Cancellation races with submission, acceptance, completion, and reconciliation; suppress late result publication while preserving verified cost.
6. Duplicate/out-of-order/replayed webhooks; invalid signatures; wrong provider account/operation ID.
7. Outbox publish succeeds but acknowledgement is lost; duplicate delivery does not create another provider attempt.
8. Concurrent same-job attempts and idempotency-key collisions; one logical reservation only.
9. Reservation remains held during unknown state; release and settle race; exactly one permitted accounting result.
10. User A cannot inspect, reconcile, cancel, or resolve User B's job/attempt.
11. Stale worker/reconciler fencing, retry cap, backoff bounds, dead-letter alerts, and audit completeness.
12. All tests use a disposable local database and fake provider. No paid provider calls.

## 9. Activation blockers

- Current migration 0013 status CHECK omits `reconciliation_required`.
- Current migration 0014 failure RPC accepts `p_retryable boolean` without provider outcome evidence.
- Current recovery RPC automatically retries expired processing jobs and finalizes expired cancellations.
- Current finish-cancel RPC can finalize without proving provider stop/zero usage.
- No attempts table, reconciliation lease/RPC, reconciliation audit table, worker, API route, or credit ledger exists.
- Repository local Supabase CLI setup/migration history and concurrency test blockers remain unresolved.

**Do not apply migrations 0013/0014, create a worker, select a provider, enable a scheduler, or connect billing until these blockers are addressed and isolated tests pass. Production must remain untouched.**
