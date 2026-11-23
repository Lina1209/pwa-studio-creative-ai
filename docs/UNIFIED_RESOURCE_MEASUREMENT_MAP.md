# Unified resource measurement map

Status: design baseline. This document defines a shared measurement vocabulary for PWA Studio. It does not add runtime instrumentation, database tables, provider calls, quotas, prices, credit deductions, or billing behavior.

## 1. Purpose and boundaries

Every creative branch should report resource consumption through one common operation/event contract while retaining branch-specific measurements. The map supports reliability, provider-cost analysis, capacity planning, and (only after separate approval) future plan/credit design.

Keep three ledgers conceptually separate:

1. **Usage facts** — what happened and which measurable units were consumed.
2. **Provider/infrastructure cost evidence** — reported, estimated, pending, unknown, reconciled, or disputed costs with source and currency.
3. **User entitlements and credits** — what a plan permits and what the user may spend. Usage facts must not directly imply a debit.

Never convert missing usage or cost to zero. Never treat a model-side estimate as an invoice-confirmed charge.

## 2. Canonical operation envelope

Every branch adapter should eventually emit the same versioned envelope:

| Field | Meaning | Rule |
| --- | --- | --- |
| `event_id` | Unique telemetry event UUID | Stable across delivery retries |
| `request_id` | User/API operation correlation UUID | Stable across the operation lifecycle |
| `user_id` | Authenticated account UUID | Nullable for explicitly supported guest flows |
| `branch` | Controlled branch identifier | e.g. `ai_companion`, `image`, `video`, `music`, `voice`, `storage` |
| `operation_code` | Controlled operation name | e.g. `chat.completion`, `image.generate`, `video.render` |
| `schema_version` | Event contract version | Required for future evolution |
| `status` | Operation lifecycle state | accepted, queued, running, succeeded, failed, cancelled, timed_out, unknown |
| `accepted_at`, `started_at`, `completed_at` | Lifecycle timestamps | UTC timestamps; nullable until known |
| `provider_configured` | Configured provider | Preserve separately from actual provider |
| `provider_actual` | Provider that handled the operation | Nullable if not known |
| `model_requested`, `model_actual` | Requested and returned model | Never silently substitute one for the other |
| `provider_request_id` | Provider job/request reference | Store only if safe and useful for reconciliation |
| `usage_dimensions` | Measured units | Populate only dimensions actually measured |
| `cost_amount`, `cost_currency` | Cost value and currency | Nullable; never assume USD if not evidenced |
| `cost_source` | Evidence source | provider response, invoice/export, verified rate card, infrastructure allocation |
| `cost_status` | Confidence/reconciliation state | reported, estimated, pending, unknown, reconciled, disputed |
| `pricing_reference` | Version/rate-card reference | Nullable until an approved rate exists |
| `safe_metadata` | Small allowlisted technical attributes | No arbitrary user content or secrets |

The operation envelope should be privacy-minimal. Do not store prompts, generated text, uploaded media contents, raw provider payloads, API keys, access tokens, or arbitrary user-supplied metadata.

## 3. Shared measurement dimensions

Use typed, nullable dimensions rather than one ambiguous generic “usage” number:

| Dimension | Unit | Applies to | Notes |
| --- | --- | --- | --- |
| `input_tokens` | tokens | text AI | Provider-reported prompt/input tokens |
| `output_tokens` | tokens | text AI | Provider-reported completion/output tokens |
| `total_tokens` | tokens | text AI | Preserve provider value; derive only under an explicitly documented rule |
| `image_count` | images | image generation/editing | Count successful outputs separately from requested variants |
| `image_pixels` | pixels | image | Width × height when actual dimensions are known |
| `audio_input_seconds` | seconds | transcription/audio understanding | Actual processed input duration |
| `audio_output_seconds` | seconds | speech/music/audio generation | Actual generated output duration |
| `audio_characters` | characters | TTS where provider bills by characters | Only if provider usage exposes it |
| `video_input_seconds` | seconds | video understanding/editing | Actual source duration processed |
| `video_output_seconds` | seconds | video generation | Actual generated duration |
| `render_seconds` | seconds | video/audio rendering | Actual compute/render wall time; distinguish from media duration |
| `job_attempts` | count | asynchronous jobs | Include retries as separate attempts or linked attempt events |
| `storage_bytes` | bytes | media storage | Snapshot or time-weighted storage measurement must be identified |
| `egress_bytes` | bytes | downloads/streaming/export | Count only when measured by infrastructure |
| `compute_seconds` | seconds | backend workers | Record worker execution separately from provider processing |
| `request_count` | count | all branches | Count accepted operations and attempts distinctly |

All durations should be stored in a consistent base unit (seconds), byte counts in bytes, and token counts as integers. Preserve source precision; do not round before storing measured facts.

## 4. Branch-by-branch measurement map

| Branch | Operation examples | Primary measured units | Secondary facts | Cost evidence to seek |
| --- | --- | --- | --- | --- |
| AI Companion | `chat.completion` | input/output/total tokens | provider, requested/actual model, latency, retries | provider usage response, verified provider invoice/export |
| Prompt Studio | `prompt.create`, `prompt.rewrite`, `prompt.translate` | input/output/total tokens | operation subtype, provider/model, latency | provider usage response, verified provider invoice/export |
| Image Studio | `image.generate`, `image.edit`, `image.upscale` | successful image count, actual pixel dimensions | requested variants, quality/size tier, model, failed attempts | provider job receipt, invoice/export, verified per-image rate |
| Video / Mini Cinema | `video.generate`, `video.extend`, `video.edit` | generated seconds, source seconds processed | resolution tier, frame rate if available, job attempts, queue/run time, model | provider job receipt/invoice; separately measured render/compute allocation |
| Video Editor / Render | `video.render`, `video.export` | render seconds, output duration, output bytes | resolution, codec, worker type, retries | compute allocation, storage and egress billing evidence |
| Music Studio | `music.generate`, `music.extend`, `music.remix` | generated audio seconds | variants, format/quality tier, model, attempts | provider job receipt/invoice or verified rate card |
| Voice Studio | `speech.generate`, `speech.clone`, `speech.transcribe`, `speech.convert` | audio input/output seconds; characters where applicable | voice/model identifier (non-sensitive), language, attempts | provider usage report/invoice or verified rate card |
| Media Library | `asset.store`, `asset.read`, `asset.delete` | stored bytes, storage duration, egress bytes | object count, retention class, region | storage and bandwidth billing exports |
| AI Companion orchestration | `workflow.run`, `workflow.step` | per-step branch units, compute seconds | parent operation ID, step status | sum of linked provider and infrastructure evidence without double-counting |
| Future branches | controlled operation codes | dimensions appropriate to the modality | schema version and lineage | verified provider/infrastructure evidence |

A workflow that invokes several branches should have a parent operation and child operation events. Aggregate from child facts; do not record the same provider charge again on the parent.

## 5. Lifecycle and asynchronous job rules

- Create a stable operation identity when the server accepts the request.
- For asynchronous providers, record accepted/queued, started, and terminal states as they become known.
- Each provider retry/attempt must be distinguishable while remaining linked to the same logical operation.
- A timeout is not proof of failure or zero usage. Mark the outcome unknown/reconciliation-required until verified.
- A cancelled operation may still have incurred provider or compute cost; capture any available usage.
- Separate successful output count from requested output count.
- Late callbacks must update/reconcile the same operation identity idempotently.
- Do not count a provider retry as a new user-requested operation.

## 6. Cost evidence and normalization

For each cost observation retain:
- amount and currency;
- source and source reference;
- observed-at timestamp;
- status/confidence;
- pricing/rate-card version, if an estimate;
- whether the value is per attempt, per operation, or an allocated infrastructure cost.

Recommended precedence is not an automatic overwrite rule: provider invoice/export is stronger financial evidence than a model SDK estimate; a verified provider receipt is stronger than an internal estimate. Preserve corrections and disagreements as an audit trail.

Infrastructure cost (compute, storage, egress) must remain separately identifiable from direct provider cost. Do not add both a provider-reported total and a derived estimate for the same charge.

## 7. Privacy, security, and retention

- Record identifiers and technical measurements, not creative content.
- Use server-generated IDs and server-owned branch/operation allowlists.
- Never accept client-supplied cost, plan, credit balance, provider price, or authoritative usage totals.
- Restrict raw event access to trusted server/operator roles; expose aggregate reports where possible.
- Define retention and deletion behavior before creating production tables, including the relationship to account deletion.
- Avoid logging provider request/response bodies, credentials, prompts, outputs, or uploaded media.
- Apply least privilege, RLS/grants review, and explicit service-role boundaries.

## 8. Current implementation versus target

**Implemented today (source-level):**
- AI Companion chat and Prompt Studio successful completions call the best-effort `record_ai_usage` writer.
- The existing `ai_usage` migration defines request/user/endpoint/provider/model, nullable token counts, nullable USD cost and source, and a timestamp.
- LiteLLM `response_cost` is labeled `litellm_response_cost`; it is not invoice-confirmed billing evidence.
- Missing token/cost values remain NULL. The writer does not store prompts or generated replies.

**Not implemented or not verified:**
- Image, video, music, voice, render, storage, and egress usage adapters.
- Canonical cross-branch event table, durable outbox, background worker, retries, dead-letter queue, and reconciliation dashboard.
- Live Supabase schema, RLS, grants, migration ledger, retention, and production write behavior.
- Complete provider invoice reconciliation or infrastructure cost allocation.
- Pricing activation, credit debits, subscriptions, payments, or plan quotas.

## 9. Rollout gates

1. Reconcile the live Supabase migration ledger, `ai_usage` table, constraints, indexes, RLS, grants, and retention. Resolve duplicate migration numbering and Storage-policy overlap before schema changes.
2. Validate existing chat/prompt telemetry in a safe test environment, including missing-usage behavior and duplicate request handling.
3. Approve the canonical event contract and operation-code registry.
4. Select a durable persistence/outbox and worker execution model; test concurrent workers, crash recovery, expired leases, timeout-after-commit, duplicate callbacks, and provider outages against disposable infrastructure.
5. Add passive adapters one branch at a time, beginning with existing text AI, then image, video, music, voice, and storage as real provider integrations become available.
6. Add read-only operational metrics and reconciliation workflows.
7. Collect representative verified cost data before considering quotas or pricing.
8. Require separate explicit approval before any production migration, provider spend control, user credit deduction, subscription, or payment rollout.

## 10. Acceptance criteria for a branch adapter

A branch is not considered instrumented until its adapter:
- emits the canonical identity, branch, operation code, schema version, and lifecycle status;
- records only measured dimensions and leaves unknown values NULL;
- distinguishes requested, successful, and retried work;
- links asynchronous attempts/callbacks idempotently;
- preserves provider and model identity;
- records cost only with amount, currency, source, and status;
- excludes private creative content and credentials;
- has tests for success, failure, missing usage, duplicate delivery, timeout/ambiguous outcome, and privacy redaction.

## 11. Safety boundary

This map is a design artifact only. No runtime behavior, schema, provider integration, cost catalog, quota, credit debit, payment, or production deployment is changed by adding it. All future changes remain subject to the rollout gates above.
