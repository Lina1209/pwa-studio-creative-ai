# Plan entitlement and usage enforcement architecture

Status: design only. This document does not activate plans, grant credits, enable checkout, or change production.

## Existing foundations

- `plan_catalog_drafts` stores immutable, versioned plan proposals. Drafts are not authoritative active plans.
- `credit_entitlement_policies` and `credit_entitlement_events` support idempotent credit grants, but the seeded `free_initial` policy is disabled and has no amount.
- AI admission limits are operational abuse/capacity ceilings. They are not customer plan quotas.
- Provider-cost budgets and customer credits remain separate accounting systems.

## Required trust model

1. Never accept a plan code, quota, user ID, or subscription status from browser input as authority.
2. Resolve the authenticated user from the verified Supabase identity.
3. Resolve that user's current entitlement from a server-owned database record.
4. Pin each assignment to an immutable plan code and version. Editing a draft must never change an existing user's limits retroactively.
5. Fail closed if the entitlement store is unavailable, the assignment is ambiguous, or its validity cannot be established.

## Proposed records

### Active plan versions

A separate approved-plan table should snapshot the validated fields from a draft: plan code/version, billing period, period days, credits per period, price/currency, limits, features, approval actor and timestamp. It should be immutable. A draft is promoted by an explicit audited operation; no automatic promotion is permitted.

### User plan assignments

A separate assignment table should contain: user ID, approved plan version, source (operator grant, free grant, or verified payment), status, starts-at, ends-at, cancellation/effective-end timestamps, and an idempotency reference. Enforce at most one currently effective assignment per user using a database constraint or transactional RPC. Keep history; do not overwrite past assignments.

### Usage reservations

A usage ledger should record user, assignment, plan version, modality/metric, quantity, request/job ID, reserved/committed/released state, and timestamps. Unique request IDs prevent duplicate counting. Reservations must be atomic in PostgreSQL so concurrent requests cannot exceed a quota.

## Enforcement flow

1. Authenticate the request and validate its payload.
2. Resolve one active assignment and immutable plan snapshot on the server.
3. Check assignment start/end and cancellation rules using database time.
4. Atomically reserve the required metric(s) against daily and monthly windows.
5. Only after successful reservation call the AI/provider.
6. Commit usage on success; release reservation on a confirmed pre-execution failure. If provider outcome is unknown, retain a bounded pending reservation and reconcile it rather than granting free retries.
7. Return remaining limits from server-calculated data; the UI is informational only.

The reservation RPC must serialize concurrent updates per user/metric (for example with row locks or advisory locks) and perform check-and-increment in one transaction. Never implement this as a read in Python followed by a separate write.

## Metric separation

Track independently:
- AI text requests;
- image generations;
- video generations and generated seconds;
- audio generations and generated seconds where applicable;
- generation jobs and parallel jobs.

A single workflow may consume more than one metric. The server must derive required metrics from the validated operation; clients cannot choose a cheaper metric label.

## Period semantics

Use database timestamps in UTC. Define daily windows consistently (UTC calendar day initially) and monthly windows as rolling 30 days unless a future product decision explicitly chooses calendar months. Store the policy/version used for every reservation. Subscription billing periods (7 or 30 days) are separate from usage windows.

## Credits and provider costs

Plan quotas, credit balance, and provider USD budgets are independent gates. A request must pass every applicable gate. A plan assignment must not itself create credits unless a separately approved, idempotent credit-grant policy explicitly says so. Provider spend limits remain server-side and must be checked before paid provider calls.

## Safe implementation sequence

1. Keep plan drafts inert (current state).
2. Add immutable approved-plan snapshots and explicit, audited admin promotion.
3. Add user assignment history and a transaction-safe, audited assignment operation.
4. Add atomic per-plan usage reservation and finalization RPCs.
5. Integrate one low-risk AI endpoint first, with tests for expiry, races, retries, unknown outcomes and fail-closed behavior.
6. Extend enforcement to image/video/audio generation jobs.
7. Only after review and explicit approval consider production migrations, deployment, free-credit activation, checkout or payment integration.

## Explicitly out of scope

This design does not authorize production migration application, deployment, plan activation, free or paid credit grants, checkout, payment processing, or provider spend.
