# Finance & Integrity Audit — foundation

Status: **backend integration implemented on this review branch; database migration is not deployed and no live database verification has been performed**.

## Scope

`backend/app/services/finance_integrity_audit.py` is a pure, read-only evaluator. It accepts explicit snapshots and returns findings. It does not connect to Supabase, issue SQL, modify balances, release holds, repair rows, or call generation providers.

The evaluator currently checks:

- credit-ledger transition continuity per user, ordered by the ledger identity sequence (`entry_id`). The identity is assigned at insert time after the wallet row is locked; `created_at` is transaction-start time and is not a safe concurrency ordering key;
- non-negative recorded balances and agreement between the latest ledger balance and a supplied wallet snapshot;
- whether the opening balance is explicitly supplied (otherwise the result is a warning, not a clean pass);
- provider cost event references to supplied generation jobs, including owner, provider, and model identity agreement;
- duplicate event IDs, per-job operation keys, and provider-scoped usage IDs;
- valid reported / estimated / unknown cost evidence;
- missing cost evidence only for jobs explicitly marked `expects_provider_cost=True`.

## Input contract

The caller must supply complete, mutually consistent snapshots:

- all ledger pages for the audited users, not just the latest page;
- wallet projections captured against a compatible snapshot boundary;
- generation jobs and provider cost events for the same audit scope;
- trusted opening balances if the audit must verify the first ledger transition.

The `complete` flag must be false whenever any source is truncated, inaccessible, inconsistently paginated, or captured across incompatible snapshot boundaries. A partial source set must never be labelled healthy.

## Status semantics

- `healthy`: complete supplied data and no findings;
- `warning`: complete data with non-critical findings, such as an unverified opening balance or explicitly expected cost evidence that is missing;
- `critical`: an invariant violation or malformed financial evidence;
- `incomplete`: no critical finding was established, but at least one source was not complete.

Critical findings take precedence over incomplete status.

## Important limitations before production integration

1. A database-backed read path and admin endpoint are now implemented on this branch: `GET /api/admin/financial/integrity/{target_user_id}` calls `get_finance_integrity_audit_snapshot(uuid)` once. The endpoint requires `admin.finance.wallets.read`, records an admin read-audit event, and returns `Cache-Control: private, no-store`. The SQL migration must be applied before the endpoint can work against Supabase.
2. It now checks credit lots, holds, and allocation totals for one user. Payment settlement/refund records and plan entitlement/assignment accounting are not yet included.
3. It does not infer that every successful job must have a provider cost event. The caller must establish expected billability from authoritative server-side policy.
4. The per-user RPC returns wallet, ledger, holds, lots, allocations, generation jobs, and provider-cost events in one SQL statement snapshot. Each source has a hard row cap (ledger 10,000; holds/lots 5,000 each; allocations/jobs/provider-cost events 10,000 each). Exact source counts are returned; any over-cap source sets `complete=false`, and the service refuses to label it healthy. This is a per-user snapshot, not a whole-platform snapshot.
5. The current database schema does not provide a dedicated compensating provider-cost event model. Corrections must not be simulated by mutating or deleting append-only rows; schema and accounting semantics require a separate reviewed migration.
6. No automated repair is permitted. Findings are evidence for administrator review only. The endpoint and migration have not been deployed to a live Supabase project; CI and database integration tests remain required.

## Tests

`backend/tests/test_finance_integrity_audit.py` covers clean input, ledger discontinuity, wallet mismatch, unverified opening balance, incomplete input, missing expected cost evidence, orphan cost events, duplicate provider usage identifiers, malformed cost evidence, invalid ledger rows, and metadata non-disclosure.

These tests are committed on an isolated review branch. They have **not** been executed in this environment; CI or a local backend test run is still required.


## Admin API contract

`GET /api/admin/financial/integrity/{target_user_id}`

- Requires the existing `admin.finance.wallets.read` permission.
- Performs exactly one service-role RPC request; it does not issue independent table reads.
- The SQL function is `STABLE`, read-only, and returns a bounded JSON snapshot plus exact row counts and limits.
- A malformed response, identity mismatch, inaccessible source, or HTTP failure returns an unavailable error; the API does not return a clean audit.
- A source above its cap is reported as `incomplete` unless a critical invariant violation was already found.
- The endpoint response contains identifiers and finding codes, but never prompts, provider metadata, usage IDs, or raw financial metadata.

## Newly covered credit invariants

- Wallet available/reserved projections equal the sums of source-separated lot balances.
- Held credit total equals the wallet reserved projection.
- Every hold's allocations match its amount and lifecycle state.
- Every allocation references an existing hold and lot belonging to the same user.
- Each lot's held allocation total equals its reserved amount.
- Duplicate allocations and duplicate hold/lot pairs are critical findings.

## Payment, subscription, and plan-quota reconciliation (migration 0100)

The expanded snapshot includes these per-user sources in the same SQL statement:
- payment orders, verified provider inbox events, and append-only order transition events;
- immutable purchase-item snapshots and payment fulfillment outbox rows;
- credit-lot source references needed to verify payment-backed credit grants;
- plan assignments, immutable assignment lifecycle events, and the approved plan versions referenced by those assignments;
- plan quota reservations and append-only quota lifecycle events.

The audit cross-checks:
- payment identity/idempotency, amount and currency against the immutable purchase snapshot;
- successful settlement against a processed, signature-verified provider success event and exactly one fulfillment outbox row;
- outbox identity against the order and completed fulfillment against the resulting credit lot or plan assignment;
- assignment ownership, plan-version identity, payment source reference, and creation event;
- quota reservation ownership against the plan assignment and generation job, plus event-key idempotency, terminal outcome, plan limit, and usage totals.

### Refund limitation — explicit, not hidden

The current schema has refunded and partially_refunded payment-order statuses, but it does not yet provide a first-class immutable refund record with refund ID, amount, currency, provider settlement reference, and event lifecycle. The current normalized provider webhook RPC accepts payment pending/succeeded/failed/cancelled events, not refund events. Therefore the audit deliberately emits refund_amounts_not_auditable and refund_lifecycle_not_implemented warnings for refunded/partially-refunded orders. It does not claim to verify refunded amounts or net settlement, and it does not attempt to infer refund values from status changes.

A separate reviewed refund foundation is still required before enabling refunds: immutable refund intents/events, provider signature verification, partial/full refund amount constraints, idempotent provider refund references, append-only compensating credit entries or entitlement suspension rules, and atomic reconciliation across payment, wallet, lot, and plan-assignment state. No automatic clawback or entitlement revocation is performed by this audit.

### Limits and operational boundaries

The expanded source caps are included in the RPC response and any over-cap source makes the snapshot incomplete. The snapshot is one user's point-in-time view, not a platform-wide reconciliation. The RPC is service-role-only and read-only. The new migration and endpoint are not deployed to a live Supabase project; production data was not accessed. The audit reports discrepancies only and never modifies payment, credit, plan, or quota state.