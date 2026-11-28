# Generation Credits Ledger — future contract

Status: design only. No wallet, ledger, debit, reservation, pricing, or payment code is implemented. The existing `generation_jobs.reserved_credits` column is a placeholder and MUST NOT be treated as a balance or as proof that credits were charged.

## Non-negotiable invariants

1. A user's balance is derived from an append-only ledger, not a mutable client-side counter.
2. Every ledger operation is idempotent. A unique operation key prevents duplicate reserve, settle, release, refund, or adjustment entries.
3. A generation job can reserve credits at most once, settle at most once, and release any unused reservation at most once.
4. A retry is another provider attempt within the same job; it is not a new customer charge or a new reservation.
5. A duplicate HTTP request with the same owner-scoped idempotency key and same canonical request fingerprint returns the existing job and reservation. The same key with a different fingerprint returns HTTP 409.
6. The backend derives owner identity from the verified Supabase JWT. Never trust owner_id, balance, price, credit quantity, or provider cost supplied by the browser.
7. No balance may become negative. Wallet locking and ledger writes must occur in one database transaction.
8. Provider cost and user credit price are different quantities. Store both explicitly; do not infer one from the other.
9. No provider request may start until the job and its credit reservation have committed successfully.
10. A database rollback cannot reverse a provider call already accepted. Provider idempotency keys and reconciliation are required to handle that external side-effect boundary.

## Proposed data model (not implemented)

### credit_wallets

- `owner_id uuid primary key references auth.users(id)`
- `available_credits bigint not null check (available_credits >= 0)`
- `reserved_credits bigint not null check (reserved_credits >= 0)`
- `updated_at timestamptz not null`

The wallet row is a transactionally maintained projection/cache. The immutable ledger remains the accounting source of truth. Reconciliation must be able to recompute the projection from ledger entries.

### credit_ledger

Append-only records with at least:

- `id uuid primary key`
- `owner_id uuid not null`
- `job_id uuid null`
- `operation_key text not null`
- `entry_type`: `grant`, `reserve`, `settle`, `release`, `refund`, `manual_adjustment`
- `available_delta bigint not null`
- `reserved_delta bigint not null`
- `currency_code text null` and `amount_minor bigint null` for separately tracked cash purchases/refunds, never floating-point money
- `metadata jsonb` restricted to an allowlist of safe audit fields
- `created_at timestamptz not null`

Constraints and indexes:
- Unique `(owner_id, operation_key)`.
- Foreign keys for owner and optional job.
- Check that each entry has a valid operation/type-specific delta shape.
- Index by `(owner_id, created_at desc)` and `(job_id, entry_type)`.
- No UPDATE/DELETE for browser roles; corrections are compensating entries, not edits to history.

A future implementation may split cash transactions and credit accounting into separate tables. Do not mix payment-provider event state with spendable credit balances.

## Atomic job creation + reservation

A future `POST /api/generation/jobs` transaction must:

1. Validate the user's JWT and derive owner_id.
2. Canonicalize and validate the request server-side; compute the request fingerprint.
3. Resolve server-controlled provider/model pricing and the maximum credit reservation. Never accept a client price.
4. Check the owner-scoped idempotency key. If an identical job exists, return that job without another ledger entry. If its fingerprint differs, return 409.
5. Lock the owner's wallet row (`SELECT ... FOR UPDATE`).
6. Verify `available_credits >= required_reservation`.
7. Insert the job, immutable `reserve` ledger entry, update the wallet projection, and insert the dispatch outbox event in the SAME database transaction.
8. Commit, then return 202. A worker must not be able to claim the job before this commit.

If any step fails, the entire transaction rolls back: no job, no reservation, no outbox event. A concurrent duplicate request must serialize on the idempotency constraint and wallet lock, then re-read the winning job rather than charging again.

## Settlement and release

- On confirmed successful completion, calculate the final charge from server-verified provider usage and the approved pricing snapshot stored with the job. In one transaction, consume the reserved amount, return unused reservation to available credits, and append one `settle` entry using a deterministic operation key such as `job:<job_id>:settle:v1`.
- On terminal failure or confirmed cancellation before provider work was billed, release the reservation once using `job:<job_id>:release:v1`.
- If the provider charged for a failed/cancelled attempt, record the actual billable cost according to the disclosed policy; do not automatically assume a full release.
- If final usage exceeds the reservation, do not silently drive the wallet negative. Apply a documented cap/overage policy and require explicit user consent for any extra charge.
- A retry does not create another reservation. Track per-attempt provider request IDs and costs separately so repeated provider calls can be reconciled without duplicating the user-facing charge.
- Settlement and release must be mutually exclusive terminal operations protected by row locks, job state predicates, and unique ledger operation keys.

## Provider-call failure window and reconciliation

A worker may call a provider successfully and crash before persisting the provider request ID, result, or cost. The database cannot provide exactly-once semantics across that external boundary.

Required safeguards:
- Send a stable provider idempotency key derived from the internal job/attempt where the provider supports it.
- Persist provider request identifiers and safe attempt metadata as soon as available.
- Keep a per-attempt record with states such as prepared, submitted, accepted, completed, failed, and unknown; avoid storing secrets or raw sensitive responses.
- Reconcile unknown attempts against provider status/billing APIs where available before retrying or releasing credits.
- Route ambiguous charges to an auditable reconciliation queue; never invent a refund or charge.
- Alert on jobs whose provider state and internal ledger state disagree.

## Security, privacy, and administration

- RLS: users may read only their own wallet summary and ledger history. No browser writes.
- All ledger mutation functions are backend-only, fixed-search-path SECURITY DEFINER where needed, with EXECUTE revoked from PUBLIC/anon/authenticated and granted only to service_role.
- Never expose service_role or allow the client to choose owner_id in RPC arguments without a server-derived identity check.
- Admin adjustments require a separately authorized, audited workflow with actor, reason code, approval context, and immutable compensating entry. Admin status must not imply unlimited credits unless a future policy explicitly defines that.
- Guest credit policy, subscriptions, cash purchase flows, multi-currency conversion, taxes, refunds, and expiry rules are intentionally out of scope until separately specified.

## Required tests before any activation

- Parallel duplicate job submissions: exactly one job, one reservation, one outbox event, one reserve ledger entry.
- Same idempotency key with changed request: HTTP 409 and no extra reservation.
- Parallel purchases/reservations at the balance boundary: balance never negative.
- Duplicate settle/release calls and settle-vs-release race: exactly one terminal accounting outcome.
- Retry after provider timeout/unknown response: no duplicate user charge; provider reconciliation exercised.
- Worker crash before provider call, after provider acceptance, after result upload, and before DB completion.
- Cross-owner read/write/RPC attempts for wallet, ledger, and job.
- Rebuild wallet projections from ledger and compare; detect drift.
- Refund, manual adjustment, overage cap, and insufficient-balance cases.
- No paid provider request is permitted in tests unless separately authorized and isolated.

## Activation rule

This document is not authorization to implement or activate billing. Before implementation, obtain explicit product approval for credit pricing, reservation size, retry charging policy, refund/expiry rules, and guest/admin treatment. Then build and test the ledger independently before connecting it to generation jobs. Until then, all credit fields remain inert placeholders.


## Additional hold/release rules for unresolved provider outcomes

A local timeout, worker crash, expired lease, or user cancellation is not proof that provider work stopped or was not billed. Therefore:

- Keep the job's credit reservation intact while any provider attempt is `submitting`, `accepted`, `unknown`, or `reconciling`. Do not release credits merely because the local job lease expired or the user cancelled the UI request.
- A cancelled job may still incur provider cost. If the provider confirms completion or billable usage after cancellation, suppress publication as requested but record the verified provider cost and apply the disclosed settlement policy. Cancellation is not a free refund guarantee.
- Release the reservation only after evidence establishes that no provider work was accepted and no billable usage occurred, or after a provider terminal failure with verified zero billable usage.
- If usage is confirmed but the final result is unavailable or suppressed, still account for verified usage. Do not fabricate a result asset or silently erase the cost.
- If provider status/billing evidence remains unavailable, leave the reservation in a durable reconciliation hold, surface an appropriate pending status to the user, and alert operations. Never settle or release based solely on elapsed time.
- Every reconciliation decision must record its evidence source, timestamp, provider operation identifier (if available), decision, and operator/system actor in an append-only audit trail. Do not store credentials or raw sensitive provider payloads.

This is a safety contract only. No wallet, ledger, reservation, reconciliation worker, or billing code is active.
