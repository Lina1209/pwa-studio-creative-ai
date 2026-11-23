# DeepSeek Vision: metering and request contract

Status: backend and gated frontend implemented on the integration branch. The feature flag remains off by default; this is not authorization to deploy or make a paid provider call.

## Verified provider behavior

DeepSeek Vision accepts image input and returns text analysis. Only `deepseek-flash` is eligible; `deepseek-v4-pro` is rejected for Vision. The official guide documents JPEG, PNG, GIF and WebP inputs, an upper bound of 1,024 image tokens per image, and image tokens billed alongside text input tokens.

The official pricing page currently lists DeepSeek Flash peak cache-miss input at USD 0.30 per million tokens and peak output at USD 1.20 per million tokens. These rates are maintained in the server-side estimator and must be re-verified immediately before any enablement.

Official references:
- https://api-docs.deepseek.com/guides/vision/
- https://api-docs.deepseek.com/quick_start/pricing/
- https://api-docs.deepseek.com/api/list-models/

## Implemented request boundary

- Authenticated `POST /api/vision/analyze`; verified account required.
- Request schema requires `consent_to_deepseek: true`; the responsive frontend shows a preview and explicit consent checkbox before sending.
- Feature flag `VISION_INPUT_ENABLED` defaults to `false`. The route returns 503 while disabled.
- Health reports `vision_analysis_enabled=true` only when the flag, DeepSeek Flash model, DeepSeek API key and server-side Supabase credentials are present. The frontend hides the Vision panel unless this health capability is true.
- Only bounded base64 data URLs for JPEG, PNG, WebP and still GIF are accepted. Remote URLs, SVG, MIME/signature mismatches, malformed base64, animation and oversized images are rejected.
- Images are decoded and re-encoded in memory to remove EXIF/GPS and ancillary metadata. No source or normalized image is stored in PWA Studio, localStorage, IndexedDB, chat history or object storage.
- The request is admitted under the distinct `vision` operation before image decoding, limiting CPU work from repeated invalid uploads.
- The typed `ask_ai_vision` service accepts only `ValidatedVisionImage`, uses `deepseek-flash`, sends the normalized data URL, disables automatic retries, and logs no image bytes, base64, prompt or provider payload.
- The API returns text analysis only; it does not echo the image, provider payload, secret or storage location.

## Shared financial controls

The estimator reserves for:
1. Canonically serialized text input, bounded by `ai_max_input_bytes`.
2. Up to 1,024 image tokens for the single accepted image.
3. Configured maximum output tokens.
4. Peak cache-miss input/output rates plus the 25% safety margin.
5. Decimal arithmetic with upward rounding.

Migration `0088_ai_provider_cost_request_modality.sql` adds an immutable `request_modality` field to the synchronous AI reservation ledger. Existing rows are classified as `text`; no historical cost is rewritten.

Service-role-only versioned RPCs `reserve_ai_provider_cost_v2` and `settle_ai_provider_cost_v2` bind reservation and settlement to the same modality. Legacy signatures remain text-only wrappers. Both modalities use the same global policy-row lock, provider budget-row lock, daily spend, and outstanding exposure ceiling. The admin report breaks out text and Vision totals while preserving combined global/provider limits.

Provider usage is used for settlement. Missing token usage or ambiguous outcomes are retained as `unknown`; the full reservation is not automatically released. Retries remain disabled because a timeout may follow provider acceptance and billing.

## Remaining launch gates

1. Publish and legally review the complete PWA Studio privacy notice and provider retention disclosure. The current consent text states that the image and prompt go to DeepSeek and refers users to the provider's terms/privacy policy, but this short notice is not a complete privacy notice.
2. Reconfirm provider model capability, pricing and token accounting immediately before deployment.
3. Run the full Python and PostgreSQL CI suite on the final integration head.
4. Obtain explicit approval before changing the production feature flag, applying production migrations or deploying.

## Required invariants

- No DeepSeek API key in browser code or responses.
- No arbitrary external URL fetch, SSRF path, public storage or browser-supplied provider file ID.
- No provider call if authentication, consent, validation, admission, cost reservation or credentials fail.
- No blind retries, no assumed zero cost, and no automatic release of unknown outcomes.
- No image generation through DeepSeek; it is text/image-input only.

The implementation is isolated on the integration branch. Production remains unchanged and no paid provider request is made by tests or this code change.
