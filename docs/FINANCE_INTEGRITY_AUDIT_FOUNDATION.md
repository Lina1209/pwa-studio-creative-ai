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
