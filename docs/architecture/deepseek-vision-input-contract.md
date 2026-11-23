# DeepSeek Vision input: safe intake contract

## Purpose

PWA Studio keeps DeepSeek as its only text/vision AI provider. DeepSeek Vision can
interpret image inputs, but it does not synthesize image outputs. This document
defines the safe intake boundary for a future, opt-in reference-image analysis
feature in Studio AI Companion and Prompt Studio.

## Implemented groundwork

`backend/app/services/vision_input.py` provides an in-memory validation and
normalization function. It:

- accepts only base64 data URLs for JPEG, PNG, WebP, and still GIF;
- rejects remote URLs, SVG, malformed base64, MIME/signature mismatches, and animation;
- applies a 5 MiB default byte limit, 20 megapixel limit, and 8192-pixel edge limit;
- decodes and verifies the image, then re-encodes pixels to strip EXIF/GPS and
  ancillary metadata before a future provider handoff;
- returns normalized MIME type, dimensions, byte length, and SHA-256 digest;
- does not write to disk, object storage, logs, or browser-visible server secrets.

The helper is connected to the authenticated `POST /api/vision/analyze` route. The route is protected by the `VISION_INPUT_ENABLED` server setting, which defaults to `false`; it returns 503 while disabled. No frontend upload/consent control is exposed yet, so the feature must remain disabled until that UI and privacy copy are implemented and reviewed.

## Required gates before provider integration

1. **Explicit user consent:** the UI must clearly state that the selected image will
   be sent to DeepSeek for analysis. No silent upload, background analysis, or
   inclusion of images in ordinary chat requests.
2. **Authentication and admission:** implemented at the backend boundary. The route requires a verified account and uses the existing PostgreSQL admission controls under the distinct `vision` operation, with the same per-user limits, global concurrency, and daily/monthly ceilings as text requests.
3. **Multimodal cost reservation:** implemented as a conservative server-side estimate using a 1,024-image-token bound, DeepSeek Flash peak cache-miss rates, maximum output tokens, and a 25% margin. The Vision reservation is atomically recorded in the same global/provider USD ledger as text. Settlement uses provider-reported usage; missing usage or ambiguous provider outcomes remain `unknown` and retain the full reserve.
4. **Provider payload contract:** use only the configured DeepSeek model and
   server-side API key. Build the multimodal `messages[].content` structure from
   validated normalized data URLs. Do not accept user-supplied remote URLs, model
   names, provider names, or arbitrary provider parameters.
5. **Request limits:** keep image count low (initially one image per request),
   enforce aggregate payload limits, timeout/concurrency bounds, and output-token
   caps. Reject animated and vector images.
6. **Privacy:** process images in memory only for the initial release. Do not persist
   source or normalized images, include image bytes in logs, or expose signed URLs.
   Explain provider-side processing/retention in the consent copy and privacy notice.
7. **Testing:** mock the provider; test payload shape, consent, auth, owner scoping,
   image validation, cost reservation rejection, timeout ambiguity, and no provider
   call when any gate fails.

## Not enabled

- The Vision endpoint exists but is disabled by default; no frontend upload/consent control is exposed.
- No image is sent to DeepSeek while `VISION_INPUT_ENABLED=false`; do not enable it until frontend consent UX, privacy copy, provider retention disclosures, and final policy review are complete.
- No provider API call, subscription, billing, or deployment is activated.
- No image-generation provider is selected; DeepSeek remains text/vision input
  only, not image output.

## Provider documentation

- DeepSeek Vision guide: https://api-docs.deepseek.com/guides/vision/
- DeepSeek model catalogue: https://api-docs.deepseek.com/api/list-models/
\n## Current backend boundary\n\nThe typed service accepts only a `ValidatedVisionImage`, reserves the Vision modality before the provider call, uses only `deepseek-flash`, disables automatic retries, and records usage under the `vision` endpoint. The route requires `consent_to_deepseek: true`, but that field alone is not a substitute for a reviewed user-facing consent flow. The feature flag remains off by default.\n