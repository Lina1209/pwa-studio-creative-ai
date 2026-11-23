# PWA Studio Operation Registry

Status: design baseline; identifiers are proposed and are not yet wired to production endpoints, billing, quotas, or credit deductions.

## Registry rules

- Operation codes are stable, lowercase, namespaced identifiers: `branch.action`.
- Do not reuse a retired code for a different meaning. Mark it deprecated and introduce a new code.
- One user-requested workflow may contain multiple child operations. Link them with a parent operation ID; never double-count the same provider or infrastructure cost on both parent and child.
- Track requested outputs, successful outputs, and attempts separately.
- Usage dimensions are nullable and populated only from measured facts. Unknown is not zero.
- Provider cost and infrastructure cost are separate evidence records; estimated cost is not invoice-confirmed.
- This registry is not a price list. Codes do not imply a credit amount or user charge.

## Core lifecycle

Logical operation states: `accepted`, `queued`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, `unknown`.

Attempt states: `started`, `succeeded`, `failed`, `timed_out`, `cancelled`, `unknown`.

A retry creates a distinct attempt linked to the same logical operation. Asynchronous provider callbacks update the same attempt/operation idempotently. A timeout is an ambiguous result until reconciled.

## Proposed operation codes

| Code | Branch | Meaning | Primary measurements |
| --- | --- | --- | --- |
| `ai_companion.chat` | AI Companion | One assistant chat completion | input/output/total tokens, latency |
| `ai_companion.workflow` | AI Companion | Orchestrated multi-step assistant workflow | child operation references, compute seconds |
| `prompt.create` | Prompt Studio | Create a prompt from an idea | input/output tokens |
| `prompt.rewrite` | Prompt Studio | Rewrite or improve a prompt | input/output tokens |
| `prompt.translate` | Prompt Studio | Translate a prompt | input/output tokens |
| `prompt.adapt` | Prompt Studio | Adapt prompt for a target model/modality | input/output tokens |
| `image.generate` | Image Studio | Generate image outputs | requested count, successful count, actual pixels |
| `image.edit` | Image Studio | Edit an existing image | successful output count, actual pixels |
| `image.upscale` | Image Studio | Upscale an image | successful output count, input/output pixels |
| `video.generate` | Video / Mini Cinema | Generate a video clip | generated seconds, resolution, attempts |
| `video.extend` | Video / Mini Cinema | Extend an existing clip | generated seconds, source seconds |
| `video.edit` | Video / Mini Cinema | AI-assisted video transformation/edit | source seconds processed, output seconds |
| `video.render` | Video Editor | Render a timeline/project | render seconds, output duration, output bytes |
| `video.export` | Video Editor | Export completed video | output duration, output bytes, egress bytes |
| `music.generate` | Music Studio | Generate a music track | generated audio seconds, variants |
| `music.extend` | Music Studio | Extend a music track | generated audio seconds |
| `music.remix` | Music Studio | Remix/transform a track | input/output audio seconds |
| `voice.generate` | Voice Studio | Text-to-speech generation | output audio seconds, characters if measured |
| `voice.clone` | Voice Studio | Voice cloning operation | provider-defined measured units; privacy-sensitive workflow controls |
| `voice.transcribe` | Voice Studio | Speech transcription | input audio seconds, tokens if returned |
| `voice.convert` | Voice Studio | Voice conversion/transformation | input/output audio seconds |
| `audio.process` | Audio Studio | Generic audio processing | input/output audio seconds, compute seconds |
| `asset.store` | Media Library | Store a generated/uploaded asset | bytes, object count |
| `asset.read` | Media Library | Read/stream an asset | bytes transferred, egress bytes |
| `asset.delete` | Media Library | Delete an asset | object count; no generation charge implied |
| `asset.export` | Media Library | Export/download an asset | bytes transferred, egress bytes |

## Shared event fields

Each future event should include:
- `event_id`, `operation_id`, optional `parent_operation_id`, and `attempt_id`;
- `user_id` or an explicit guest identity class;
- `branch`, `operation_code`, `schema_version`, lifecycle `status`;
- accepted/started/completed timestamps;
- configured and actual provider/model identifiers where known;
- measured usage dimensions and units;
- cost amount, currency, source, status, and pricing reference when evidenced;
- a small allowlist of safe technical metadata.

Never place prompts, generated text, media contents, credentials, API keys, or arbitrary client metadata in telemetry events.

## Provider and model identity

Store the requested provider/model separately from the actual provider/model. Record a fallback or routing change explicitly; do not silently attribute usage to the requested model when another model served the request. Provider request/job identifiers may be retained only where safe and needed for status polling or reconciliation.

## Idempotency and aggregation

- `event_id` is stable across delivery retries.
- `operation_id` identifies the logical user action.
- `attempt_id` distinguishes provider/worker attempts.
- Enforce idempotency at persistence boundaries; do not rely only on in-process memory.
- Aggregate branch totals from child events/attempt evidence with explicit deduplication.
- Parent orchestration events must not duplicate child provider charges.
- Corrections should append/reconcile evidence rather than silently overwrite historical financial observations.

## Not yet registered as billable

The following are deliberately not assigned prices or credit costs: every code in this registry. There is no approved rate catalog in production. Some actions may be free, bundled, internally processed, or have provider-specific costs. That decision requires measured usage and verified provider/infrastructure rates.

## Implementation sequence

1. Reconcile live Supabase schema, migration ledger, RLS, grants, and Storage policies.
2. Approve this operation-code registry and canonical event schema.
3. Implement durable persistence/outbox and idempotent worker processing in disposable test infrastructure.
4. Instrument existing chat and prompt operations as passive telemetry.
5. Add adapters only when each branch's real provider and lifecycle are known.
6. Validate duplicate callbacks, retries, crashes, timeout-after-commit, missing usage, and privacy redaction.
7. Build read-only operational reporting and provider-cost reconciliation.
8. Consider quotas/pricing only after verified cost observations and separate approval.

## Safety boundary

This document adds identifiers and design rules only. It does not change runtime behavior, database schema, provider calls, production data, plan entitlements, quotas, pricing, credits, payments, or deployment.
