# Provider cost telemetry and unit-economics plan

Status: implementation plan based on the current backend source. This document does not add a database migration, change provider calls, enable credit deductions, or claim that provider cost data is complete.

## 1. What exists today

The current AI path returns a structured `AIResult` containing:
- input, output, and total token counts when the provider reports them;
- actual model name returned by the provider;
- optional USD cost from LiteLLM's `response_cost`;
- a cost-source label (`litellm_response_cost`) when that value is available.

The current `record_ai_usage` service makes a best-effort insert into the existing Supabase REST table `ai_usage`. It records request ID, authenticated user ID, endpoint, configured provider, actual model, token counts, optional cost, and cost source. It deliberately excludes prompts, replies, and credentials. Telemetry failure is logged without failing a successful user-facing AI response.

This is a useful starting point, but not yet a complete financial or provider-cost ledger:
- the write is best-effort and can be lost when Supabase is unavailable;
- the live `ai_usage` schema and migration history have not yet been reconciled in this audit;
- a missing cost is unknown, not zero;
- token usage does not capture image, video, audio, storage, bandwidth, or worker costs;
- configured provider and actual returned model can differ;
- no cost aggregation, budget alert, retention policy, or reconciliation dashboard is implemented.

## 2. Measurement principles

1. Record provider-reported usage and provider-reported cost separately from estimates.
2. Every cost value must carry currency, source, and confidence/status. Never silently convert missing cost to zero.
3. Preserve the configured provider, actual provider, requested model, and actual model as distinct fields where available.
4. Keep provider cost telemetry separate from user credits and the credit ledger.
5. Use a stable operation/request ID for retries and callbacks; deduplicate events.
6. Keep telemetry privacy-minimal: no prompts, generated content, API keys, raw provider payloads, or unnecessary personal data.
7. A telemetry write failure must not turn a completed generation into a failed user experience, but it must be observable and recoverable.
8. Establish provider-level global spend ceilings and alerts independently of plan quotas and user credit balances.

## 3. Proposed canonical usage event

A future normalized event should contain:

- identity: `event_id`, `request_id`, `user_id` (nullable for guest), `branch`, `operation_code`;
- lifecycle: `accepted_at`, `started_at`, `completed_at`, `status`, `reconciliation_status`;
- provider: `provider_configured`, `provider_actual`, `model_requested`, `model_actual`, `provider_request_id`;
- measured usage: `input_tokens`, `output_tokens`, `image_count`, `audio_seconds`, `video_seconds`, `render_seconds`, `storage_bytes`, `egress_bytes` (only relevant dimensions populated);
- cost: `cost_amount`, `cost_currency`, `cost_source`, `cost_status`, `pricing_reference`;
- safe metadata: dimensions, resolution tier, duration tier, region, and non-sensitive job metadata;
- timestamps and schema version.

Recommended cost statuses: `reported`, `estimated`, `pending`, `unknown`, `reconciled`, `disputed`. Cost source should identify provider response, provider invoice/export, internal rate card, or infrastructure allocation.

Do not add all these columns to the existing `ai_usage` table blindly. First inspect the actual Supabase migration ledger and table definition. Decide whether to evolve `ai_usage` or create a separate append-only `provider_usage_events` table with a clear ownership boundary.

## 4. Capture by creative branch

| Branch | Primary measured units | Cost evidence |
| --- | --- | --- |
| AI Companion / Prompt Studio | input and output tokens, actual model | provider usage and provider-reported cost |
| Image Studio | image count, dimensions, quality/model | provider job receipt or invoice; per-image estimate only when labeled |
| Video / Mini Cinema | generated seconds, resolution, model, retries | provider job receipt, render time, infrastructure allocation |
| Music Studio | generated audio seconds, model, variants | provider job receipt or provider invoice |
| Voice / Audio | input/output audio seconds, characters where applicable | provider usage report and provider rate card |
| Storage / exports | stored bytes over time, egress bytes, render duration | storage and bandwidth billing exports; compute allocation |

Do not assume all providers expose per-request costs. Where they do not, preserve raw measured units and calculate an explicitly labeled estimate from a versioned rate card after rates are verified.

## 5. Reliability and reconciliation

- Persist an operation acceptance record before asynchronous work is queued.
- Use an outbox or durable event queue for usage events once infrastructure is selected; avoid relying on process memory.
- Retry telemetry writes with bounded exponential backoff and idempotent event IDs.
- Do not log raw request/response bodies or secrets during retry failures.
- Reconcile completed jobs against provider receipts and invoices.
- Mark missing or conflicting provider usage as pending/unknown; never infer zero.
- Track late callbacks, duplicate callbacks, retries, provider timeouts, and jobs whose final state is ambiguous.
- Keep a correction history rather than silently overwriting previously reported cost.

## 6. Unit-economics reporting

Once enough verified data exists, aggregate by provider, model, branch, operation, day, and plan cohort:
- total requests and successful/failed jobs;
- measured units and missing-usage rate;
- reported versus estimated cost;
- cost per successful operation and per user;
- retry and cancellation cost;
- infrastructure allocation and storage/egress cost;
- gross margin only after payment revenue and fee data are verified.

Do not publish plan prices or included quotas from a small or incomplete sample. Include safety margin for retries, infrastructure, payment fees, taxes where applicable, currency conversion, and provider price changes.

## 7. Rollout sequence

1. Confirm the existing `ai_usage` table definition, RLS, grants, retention, and migration ownership from the live Supabase migration ledger. No SQL is applied during this step.
2. Validate that current DeepSeek/LiteLLM responses consistently provide token counts and determine when `response_cost` is absent. Record missingness explicitly.
3. Add tests around telemetry payload shape, idempotency, redaction, and failure behavior before changing the schema.
4. Add passive, durable cost telemetry for AI Companion and Prompt Studio; do not deduct user credits.
5. Add provider receipt capture for image, video, music, and voice integrations as those integrations are implemented.
6. Add read-only admin cost reports and provider budget alerts.
7. Measure costs over a representative period, then approve plan limits and operation pricing.
8. Only after separate explicit approval, connect priced operations to wallet reservations and settlement.

## 8. Current safety boundary

The existing AI telemetry is best-effort and currently covers the chat and prompt endpoints. It is not a complete platform cost model. No subscription billing, provider budget enforcement, user credit deduction, or payment integration is activated by this plan. The pricing catalog remains empty until verified provider rates and a credit conversion policy are approved.
