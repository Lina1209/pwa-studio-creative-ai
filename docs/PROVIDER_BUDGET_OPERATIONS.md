# Global AI provider budget controls

**Status:** implemented in the review branch as migration source and SQL integration coverage. Not applied to any live Supabase project. The budget policy is intentionally disabled until an operator configures real USD limits.

## What the controls protect

The database now has two independent global limits shared by every generation worker and every job:

- **Daily provider spend ceiling (USD):** known provider cost events recorded during the current UTC calendar day plus all still-open reservations must fit under this limit.
- **Outstanding exposure ceiling (USD):** the sum of every active or unknown per-job reservation must fit under this limit, regardless of when the reservation was created.

The admission RPC locks one singleton policy row before checking and inserting a reservation. That lock serializes admissions across different jobs, so two workers cannot both observe the same remaining budget and overbook it.

Each reservation is based on the immutable job pricing snapshot field `maximum_provider_cost_usd`. The existing per-job cap remains in force.

## Reservation lifecycle

- `reserved`: maximum provider cost has been reserved before the first billable provider call.
- `settled`: known provider cost evidence was appended to the cost ledger; actual spend is counted in the UTC daily total.
- `unknown`: provider usage exists but its charge is unknown. The full reservation remains counted against outstanding exposure.
- `released`: an operator explicitly verified that the provider did not charge. A timeout, missing response, expired worker lease, generic exception, or missing usage object is not sufficient evidence.

A worker lease expiring never releases a provider reservation. If a result arrives without a provider usage contract, the reservation remains open for reconciliation. The cost ledger remains append-only.

## Operator configuration

The singleton policy is created disabled with both monetary limits unset. No sample or production budget amount is embedded in the migration.

A trusted operator must configure both positive USD values through the service-role-only RPC:

`public.configure_provider_budget_policy(daily_budget_usd, max_outstanding_reserved_usd)`

Passing either value as NULL disables admission. The browser must never receive the service-role key or be allowed to submit either limit. Do not add these values to frontend configuration.

Choose the amounts from actual available operating capital, provider billing terms, and the acceptable maximum loss/exposure. They are business-risk decisions, not user-facing subscription prices; they must not be guessed by the application.

## Reconciliation

Use `public.resolve_generation_provider_reservation(job_id, resolution_key, resolution, actual_cost_usd, note)` only after reviewing provider billing evidence.

- `release_no_charge`: use only when the provider's records prove that no billable operation was created. The actual-cost argument must be NULL.
- `settle_known_cost`: use when the provider's records establish the amount but the normal usage callback was missing. Supply the verified amount and a unique resolution key. This appends an estimated/reconciled ledger event and settles the reservation.

The resolution note must explain the evidence. These RPCs are service-role-only. Keep an operator audit trail outside the application as well.

Legacy unknown-cost events that cannot be associated with a valid per-job USD ceiling remain global admission blockers. They require a privileged database operator to investigate and repair; do not invent a zero or release them automatically.

## Validation and rollout boundary

The SQL integration suite covers disabled-policy denial, idempotent reservation, a second job being denied by the shared exposure limit, known-cost settlement, unknown-cost retention, lease-expiry retention, UTC daily spend rollover, and least-privilege RPC grants.

These checks are committed as test source; they are **not reported as executed** until the repository's PostgreSQL migration test workflow returns a successful run.

Before enabling generation in production:

1. Review migration 0026 and the test suite.
2. Apply the migration only through the approved Supabase migration process after explicit production authorization.
3. Configure actual daily and outstanding USD limits using a trusted operator session.
4. Run controlled provider billing tests and reconcile invoices against the cost ledger.
5. Keep worker runtime and public generation endpoints disabled until all checks pass.

No migration, production budget setting, provider call, payment activation, or deployment was performed by this review.
