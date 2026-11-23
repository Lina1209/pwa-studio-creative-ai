# Plan approval and assignment foundation

Migration: `0060_plan_approval_and_assignment_foundation.sql`

Status: inert database foundation only. No API endpoint or RPC is installed to approve plans, assign plans, activate subscriptions, or grant credits.

## Tables

- `approved_plan_versions`: immutable snapshot copied from a plan draft by a future explicitly audited approval operation. It retains the source draft and the exact limits/features that were approved.
- `user_plan_assignments`: append-only assignment snapshot tied to one approved plan version, with user, source, idempotency key, validity interval and creator.
- `user_plan_assignment_events`: append-only lifecycle audit history for future assignment transitions.

All three tables have RLS enabled and no public, anon, or authenticated grants. Only the backend service role has table access. Update/delete triggers make the records immutable.

## Important boundaries

- A draft is not an approved plan.
- An approved plan version is not a subscription.
- An assignment row does not itself grant credits or enable checkout.
- No assignment can be created through the browser.
- No active plan resolution or quota enforcement is implemented by this migration.
- No production migration has been applied.

## Required next implementation

A reviewed backend-only approval RPC must validate and copy a draft atomically, enforce unique plan code/version, and record an approval reason and actor. A separate assignment RPC must verify the approved version, validate source and time window, enforce idempotency, and append the initial lifecycle event in the same transaction.

Future activation/cancellation/expiry transitions must be append-only events and transactionally enforce non-overlapping effective assignments. The server must resolve current assignments using database time and fail closed on ambiguity or storage failure.

Before connecting usage quotas, implement and test atomic reservation RPCs with concurrent requests, retries, expiry boundaries and unknown provider outcomes.
