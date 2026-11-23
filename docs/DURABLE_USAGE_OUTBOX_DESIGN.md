# Durable provider-usage event delivery — design proposal

Status: design-only. This document does not create a table, migration, background worker, queue, or runtime behavior. It must not be treated as evidence that usage events are durably delivered today.

## 1. Current delivery guarantee

The current chat and Prompt Studio request path calls `record_ai_usage` after a successful AI completion. It performs one best-effort REST insert into `public.ai_usage` with a short timeout. The user response is not failed if telemetry persistence fails.

This protects user experience, but it is **at-most-one-attempt best effort**, not durable delivery. A process crash, timeout, transient network error, Supabase outage, or insert conflict can leave a gap. The current schema's unique `request_id` can help prevent duplicate rows, but does not itself provide retry or event recovery.

## 2. Target guarantee

Adopt an outbox pattern only after live schema and migration history are reconciled:

1. Capture a minimal usage event with a stable server-generated event/request UUID.
2. Persist it durably before considering telemetry accepted.
3. Deliver asynchronously to the analytical usage table.
4. Retry transient failures with bounded exponential backoff and jitter.
5. Make delivery idempotent using a unique event ID / request ID.
6. Move exhausted or structurally invalid events to a visible dead-letter state for operator review.
7. Preserve user-facing generation success even if the telemetry pipeline is temporarily unavailable, while exposing telemetry health to operators.

The outbox's own persistence is a separate reliability boundary: if the durable write fails, record a metric/alert through an independent channel. Do not silently claim the event was captured.

## 3. Proposed event lifecycle

Suggested states:
- `pending`: captured and waiting for delivery;
- `processing`: claimed by a worker with a lease;
- `delivered`: destination insert confirmed;
- `retryable_failure`: transient failure; eligible after `next_attempt_at`;
- `dead_letter`: retry budget exhausted or permanent schema/validation failure;
- `reconciliation_required`: destination outcome ambiguous (for example, timeout after request may have committed); worker must query by stable ID before deciding whether to resend.

Worker claims should use a lease/claim token and a bounded batch. Stale `processing` leases must become eligible again after expiry. Avoid holding database transactions open during external HTTP calls.

## 4. Proposed event envelope

A minimal envelope can include:
- `event_id` UUID (stable and unique);
- `request_id` UUID (correlation with the existing AI usage row);
- nullable `user_id`;
- `branch` and `operation_code`;
- `provider_configured`, `provider_actual`, `model_requested`, `model_actual`;
- nullable measured input/output tokens and other provider-specific unit fields;
- nullable `cost_amount`, `cost_currency`, `cost_source`, `cost_status`;
- operation status and timestamps;
- schema version and a small allowlisted metadata object.

Never store prompts, generated text, raw provider request/response bodies, API keys, access tokens, or arbitrary user-supplied metadata in the outbox.

## 5. Retry and idempotency policy

- Retry only transient network errors, rate limits, and retryable 5xx responses.
- Respect provider/Supabase `Retry-After` when present.
- Use exponential backoff with jitter and a bounded attempt count / maximum age.
- Treat validation errors and schema mismatches as permanent until code/schema is corrected.
- On ambiguous write timeout, first query the destination by `request_id`; do not blindly duplicate.
- Use a unique constraint on the event/request identity at the destination.
- Preserve original event data and append delivery-attempt metadata; do not overwrite measured usage or cost during retries.

## 6. Operational signals

Expose read-only operator metrics:
- pending, processing, retryable, and dead-letter counts;
- oldest pending event age;
- delivery success/failure rates;
- attempt count distribution;
- ambiguous outcome count;
- destination latency and telemetry-write failure rate;
- event volume and missing-usage/cost rates by provider/model/branch.

Alert on sustained queue growth, oldest-event age, dead-letter growth, and sudden increases in missing provider usage. Avoid including user prompts or private content in logs or alerts.

## 7. Schema and rollout prerequisites

Before implementation:
1. Inspect the actual Supabase migration ledger and deployed `ai_usage` table, constraints, indexes, RLS, grants, and retention.
2. Resolve the duplicate `0005` migration version and Storage policy overlap; do not replay migrations blindly.
3. Decide whether the outbox and normalized usage events belong in a new table or an existing event/queue service.
4. Confirm transaction and worker execution model, service-role permissions, retention, cleanup, and dead-letter review ownership.
5. Test duplicate delivery, worker crash, expired leases, timeout-after-commit, concurrent workers, and Supabase outage against disposable PostgreSQL/Supabase.
6. Add metrics for the telemetry pipeline itself.

No migration or worker should be deployed until these checks pass and the schema rollout is explicitly approved.

## 8. Current safety boundary

No durable outbox is implemented by this proposal. Current `ai_usage` writes remain best-effort. No user credit deduction, payment, pricing activation, or production schema change is part of this design.
