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

The helper is deliberately not connected to an API route yet.

## Required gates before provider integration

1. **Explicit user consent:** the UI must clearly state that the selected image will
   be sent to DeepSeek for analysis. No silent upload, background analysis, or
   inclusion of images in ordinary chat requests.
2. **Authentication and admission:** require a verified account and extend the
   existing PostgreSQL AI admission controls with a separately named vision
   operation, per-user limits, global concurrency, and daily/monthly limits.
3. **Multimodal cost reservation:** the current cost estimator counts serialized
   UTF-8 request bytes and text output tokens. It is not a valid reservation model
   for image-token billing. Before enabling Vision, add a conservative,
   server-maintained image-token estimator or a bounded fixed image exposure,
   reserve the maximum expected USD amount atomically, and settle/mark unknown
   using the existing cost journal. Never bypass the cost admission gate.
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

- No Vision endpoint or frontend upload control is exposed.
- No image is sent to DeepSeek by this change.
- No provider API call, subscription, billing, or deployment is activated.
- No image-generation provider is selected; DeepSeek remains text/vision input
  only, not image output.

## Provider documentation

- DeepSeek Vision guide: https://api-docs.deepseek.com/guides/vision/
- DeepSeek model catalogue: https://api-docs.deepseek.com/api/list-models/
