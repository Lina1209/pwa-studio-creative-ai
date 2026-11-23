# Finance & Integrity Audit — foundation

Status: **isolated implementation foundation; not production-connected**.

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

1. This is not yet a database-backed audit runner or admin endpoint.
2. It does not yet verify hold-to-lot allocation totals, payment settlement/refund records, plan entitlements, or reconciliation across every financial table.
3. It does not infer that every successful job must have a provider cost event. The caller must establish expected billability from authoritative server-side policy.
4. It cannot prove a consistent point-in-time snapshot across multiple PostgREST requests. Production integration needs a database-side snapshot/RPC or another explicit consistency mechanism.
5. The current database schema does not provide a dedicated compensating provider-cost event model. Corrections must not be simulated by mutating or deleting append-only rows; schema and accounting semantics require a separate reviewed migration.
6. No automated repair is permitted. Findings are evidence for administrator review only.

## Tests

`backend/tests/test_finance_integrity_audit.py` covers clean input, ledger discontinuity, wallet mismatch, unverified opening balance, incomplete input, missing expected cost evidence, orphan cost events, duplicate provider usage identifiers, malformed cost evidence, invalid ledger rows, and metadata non-disclosure.

These tests are committed on an isolated review branch. They have **not** been executed in this environment; CI or a local backend test run is still required.
