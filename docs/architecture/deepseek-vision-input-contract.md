# DeepSeek Vision input: safe intake contract

## Purpose

PWA Studio uses DeepSeek as its only text and image-understanding provider.
DeepSeek Vision interprets image inputs; it does not synthesize image outputs.
The feature is intended for Studio AI Companion and Prompt Studio, where a
creator can ask for analysis of a visual reference, frame or sketch.

## Implemented backend boundary

`backend/app/services/vision_input.py` validates and normalizes images in memory:

- accepts base64 data URLs for JPEG, PNG, WebP and still GIF;
- rejects remote URLs, SVG, malformed base64, MIME/signature mismatches and animation;
- enforces 5 MiB, 20 megapixels and an 8,192-pixel edge limit;
- decodes and verifies pixels, then re-encodes them to strip EXIF/GPS and ancillary metadata;
- returns normalized MIME type, dimensions, byte length and SHA-256 digest;
- never writes source or normalized image bytes to disk, object storage or logs.

The authenticated `POST /api/vision/analyze` route requires the explicit
`consent_to_deepseek: true` field. It records distributed request admission
before image decoding, then validates the image and calls the typed
`ask_ai_vision` service. The service accepts only a `ValidatedVisionImage`,
uses only `deepseek-flash`, disables automatic retries, reserves the Vision
modality in the shared global/provider USD ledger before transmission, and
settles from provider usage. Missing usage or ambiguous provider outcomes remain
`unknown` and retain the full reservation.

The endpoint is disabled unless both `VISION_INPUT_ENABLED=true` and `VISION_PRIVACY_REVIEW_APPROVED=true` are explicitly configured. The second setting is an independent legal/privacy release gate and defaults to false. The health endpoint
reports `vision_analysis_enabled=true` only when the flag, DeepSeek Flash model,
DeepSeek API key and server-side Supabase credentials are present. The frontend
upload/preview and explicit consent panel are implemented; the panel remains
hidden unless health reports the capability enabled.

## Consent and privacy

Before the feature may be enabled in a public deployment, PWA Studio must publish
a complete privacy notice that identifies DeepSeek as the external recipient and
explains provider-side processing and retention under the provider's applicable
terms and privacy policy. The current consent panel already states that the image
and prompt are sent to DeepSeek, that PWA Studio does not persist the source image,
and that users must not submit confidential materials and must have rights to use
the image. That short notice is not a substitute for the complete privacy notice
or final legal/policy review.

The browser holds the selected image in memory, previews it through a temporary
object URL, and posts the normalized data URL directly to the authenticated
backend only after the user checks the consent box and presses Analyze. The
frontend does not place image bytes in localStorage, IndexedDB, chat history or
the media library. The backend does not persist them or include them in logs.

## Admission and cost controls

- Vision is a distinct distributed AI admission operation with the same per-user,
  per-minute, daily, monthly and global concurrency ceilings as text requests.
- The image is bounded to one per request and a maximum of 1,024 image tokens.
- Reservation uses the peak DeepSeek Flash cache-miss input/output rates, maximum
  output tokens and a 25% safety margin.
- Text and Vision share the same global daily budget, provider daily budget and
  outstanding exposure ceiling. No separate Vision budget can bypass text limits.
- A reservation is created before the provider call. Unknown outcomes are never
  assumed to cost zero and are not automatically released.
- The browser cannot choose the provider, model, token count, price or request
  modality. The service derives all of these on the server.

## Remaining launch gates

1. Publish and legally review the complete product privacy notice and provider
   retention disclosure.
2. Reconfirm DeepSeek Vision support, pricing and token accounting immediately
   before any deployment or enablement.
3. Run the full Python and PostgreSQL CI suite on the final integration head.
4. Obtain explicit approval before changing the production feature flag or
   deploying the feature.

## Not enabled

- `VISION_INPUT_ENABLED` defaults to `false`.
- No image is sent to DeepSeek while the flag is false.
- No production migration, deployment, billing change or paid provider call is
  authorized by this implementation.
- No image-generation provider is selected; DeepSeek remains text/Vision input
  only, not image output.

## Provider documentation

- DeepSeek Vision guide: https://api-docs.deepseek.com/guides/vision/
- DeepSeek model catalogue: https://api-docs.deepseek.com/api/list-models/
