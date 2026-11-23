# DeepSeek Vision: metering and request contract

Status: design only. No Vision endpoint is enabled by this document.

## Verified provider behavior

The only supported text/vision provider remains DeepSeek, using `deepseek-flash`. The official Vision guide documents image content blocks in OpenAI-compatible Chat Completions and Responses requests. Images are input-only; the response is text. Supported input formats are JPEG, PNG, GIF and WebP.

Official references:
- Vision guide: https://api-docs.deepseek.com/guides/vision/
- Model pricing: https://api-docs.deepseek.com/quick_start/pricing/
- Responses API: https://api-docs.deepseek.com/guides/responses_api/

The Vision guide states that images are resized before inference and have an upper bound of 1,024 image tokens per image. Image tokens are billed as input tokens alongside text tokens. The official pricing page currently lists the DeepSeek Flash peak cache-miss input rate at USD 0.30 per million tokens and peak output at USD 1.20 per million tokens. These are the conservative rates already used by the server-side text cost estimator. Prices must be re-verified before enabling Vision and updated in one reviewed server-side price table.

## Non-negotiable request boundary

- Vision must use the existing authenticated server-side AI boundary; never expose the DeepSeek API key.
- Only `deepseek-flash` is eligible for image input. `deepseek-v4-pro` must be rejected for Vision because the official model catalogue marks Vision unsupported.
- Only user-provided, validated image bytes may be transmitted. Do not accept arbitrary external URLs, fetch URLs from the backend, or let a client provide provider file IDs. This avoids SSRF and cross-account file access.
- Use the validated image bytes or a server-owned private temporary object. No public bucket and no public URL.
- Require an explicit user action and clear notice that the image will be sent to DeepSeek for analysis. Do not send images automatically from a project or chat history.
- Never log prompts, image bytes, base64 payloads, signed URLs, API keys, or provider request bodies.
- Delete temporary image material after the request or a short bounded retention period; failure cleanup must be observable without exposing content.
- Keep the existing strict image validation limits (5 MiB, 20 megapixels, real MIME/magic-byte inspection, EXIF removal, no SVG/HTML, and no animated image payloads). The provider accepts GIF, but the product contract deliberately accepts only static images.
- Limit one image per request initially. A future multi-image feature requires explicit new limits and cost tests.
- Limit user text and model output independently. Keep retries disabled: a timeout may follow a billable provider acceptance.

## Cost admission requirements

The current text path reserves a worst-case USD amount atomically in PostgreSQL before calling DeepSeek, then settles from provider-reported usage. Vision must use the same global and per-user/provider budget ledger and the same fail-closed behavior; it must not create a second uncoordinated budget.

A Vision reservation must include:
1. Text input upper bound, calculated from the canonical text-only request representation (never count base64 bytes as tokens).
2. Up to 1,024 image input tokens for each accepted image, per the provider's documented upper bound.
3. The configured maximum output tokens.
4. Peak cache-miss rates for both input and output, plus the existing 25% safety margin.
5. Decimal arithmetic and upward rounding.

The reservation must be persisted before any provider request. If cost policy is missing, prices are stale/unverified, the ledger is unavailable, or the reservation is denied, return a safe unavailable/limit response without contacting DeepSeek. After a successful response, settle using provider-reported prompt/completion token usage. If usage is missing or the request outcome is ambiguous, keep the reservation unresolved for operator reconciliation; never assume zero cost or release it automatically.

Do not assume that provider usage exposes a separate image-token count. Total prompt tokens must be treated as the authoritative input usage if the provider reports it. Record the request modality (text or vision) as non-sensitive metadata in the usage ledger so operators can distinguish usage classes. This metadata change must preserve existing idempotency and append-only/audit guarantees.

## API and UX contract before implementation

- Add a dedicated opt-in endpoint or an explicit typed multimodal request path; do not silently change the existing text-only `ask_ai` contract.
- Validate authentication, content safety, image count, byte size, pixel count, format and decoded image dimensions before reservation.
- The API accepts image bytes only through a bounded upload/body mechanism. It must not accept a URL, data URI, filesystem path, bucket path, or provider file ID from the browser.
- Return only text analysis and safe request metadata; never echo the image, provider payload, secret, or storage location.
- The UI must explain that the selected image is sent to DeepSeek and may incur AI usage cost before the user confirms.
- Enforce existing request-rate, daily, monthly and concurrent limits, and add a modality-specific limit if abuse testing shows it is needed.
- Keep feature flag off by default. No provider call or production enablement occurs as part of implementation or CI.

## Required tests

1. Vision uses only `deepseek-flash`; Pro and unknown models fail before network access.
2. The image upper bound is 1,024 input tokens per image and is included in worst-case reservation.
3. Base64 expansion is excluded from token estimation; validated image count and canonical text size are included.
4. Peak cache-miss input/output rates and the 25% safety margin are used.
5. Atomic reservation denial or unavailable ledger prevents provider invocation.
6. Provider exception/timeout marks cost unknown and does not retry.
7. Missing usage does not release the reservation.
8. Owner authentication, consent, content safety, request size and rate limits are enforced.
9. No arbitrary URL fetch, public storage, or browser-visible provider credential exists.
10. Feature flag defaults off and health reports Vision unavailable until all dependencies are explicitly enabled.

## Current implementation boundary

The existing `ask_ai` implementation and `ai_cost_admission` service are text-only. Their message schema and byte estimator must not be widened casually to accept multimodal blocks. Implement Vision through a separate typed service that shares the same atomic budget RPC after the reservation estimator has been extended and covered by tests. This document is a design checkpoint, not authorization to make a paid request, configure a key, deploy, or enable the feature.


## Modality-aware cost admission checkpoint (2026-11-23)

Implemented on the integration branch:

- The pure `estimate_worst_case_vision_cost` estimator accepts canonical text messages and exactly one validated image count, applies the 1,024 image-token bound, peak DeepSeek Flash rates and the 25% safety margin, and rejects Pro/unknown models.
- Migration `0088_ai_provider_cost_request_modality.sql` adds an immutable `request_modality` column (`text` or `vision`) to the synchronous provider reservation ledger. Existing rows are classified as `text`; historical costs are not rewritten.
- Versioned service-role-only RPCs `reserve_ai_provider_cost_v2` and `settle_ai_provider_cost_v2` bind each reservation and settlement to the same modality. Legacy RPC signatures remain as text-only wrappers for compatibility.
- Text and Vision reservations take the same global policy-row lock and provider budget-row lock. Global daily spend, provider daily spend and outstanding exposure include both modalities; no separate Vision budget can bypass the shared ceiling.
- Request modality is checked during idempotent reservation replay, checked again at settlement, and protected by a database trigger against mutation.
- The admin synchronous AI budget report exposes settled estimates, active reserves and unknown counts separately for `text` and `vision`, while provider/global totals continue to include both.
- The backend exposes a typed `reserve_ai_provider_vision_cost` admission helper. It performs no provider request; a dedicated Vision transport/service, image consent flow and feature-flagged endpoint remain out of scope.

Unit tests cover text and Vision reservation metadata, shared RPC usage, modality-bound settlement and fail-closed mismatch handling. A transactional PostgreSQL test script covers shared-budget denial, idempotency conflict, modality immutability and settlement binding; it must run in CI before this migration is considered validated.

This checkpoint does not authorize a paid provider call, production migration, key configuration, deployment or feature enablement. Vision remains unavailable until the complete typed request path and its integration tests are reviewed.
\n## Backend implementation status (2026-11-23)\n\nThe authenticated `POST /api/vision/analyze` endpoint now requires `consent_to_deepseek: true`, strict in-memory image validation, distributed per-user/global admission under the `vision` operation, and the shared USD reservation ledger. `VISION_INPUT_ENABLED` defaults to `false`. The responsive frontend upload/preview and explicit consent interaction are implemented, but the complete product privacy notice, provider retention disclosure and final policy/legal review are still outstanding, so enabling the flag is prohibited.\n