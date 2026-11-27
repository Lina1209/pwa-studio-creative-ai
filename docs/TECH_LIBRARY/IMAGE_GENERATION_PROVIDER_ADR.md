# ADR: image-generation provider boundary for PWA Studio

- Status: proposed architecture; no provider selected or enabled.
- Date: 2026-11-27.
- Scope: future image-reference handoff from the Character Library and Mini Movie Studio.

## Findings from the current branch

The backend currently has one text-generation path:
- `POST /api/chat` and `POST /api/prompts` call `ask_ai()`.
- `ask_ai()` uses LiteLLM `completion()` with text chat messages.
- Current configured primary is DeepSeek Flash.
- Settings already contain provider credentials for DeepSeek, OpenAI, Anthropic and Ollama, but that does not mean every provider is configured or that image generation is implemented.
- There is no image/video generation endpoint, provider adapter, media job queue, image payload validation pipeline, provider webhook, or completed generated-media storage workflow in this branch.
- The current Character Library cloud backup is a separate feature and is not a generation authorization mechanism.

## Decision

Keep DeepSeek as the active text assistant. Do not route images through `/api/chat` or the generic LiteLLM completion path.

Treat image generation as a separate capability with its own:
- server-only provider credential;
- authenticated endpoint and explicit capability/feature flag;
- provider adapter interface;
- owner-checked asset resolver;
- upload/size/format validation;
- explicit consent screen naming the external provider and exact selected references;
- asynchronous job lifecycle, idempotency key, timeout and bounded retry policy;
- usage/cost accounting and private output storage;
- deletion/retention policy and audit metadata.

No provider key, environment variable, payment method, provider account, or production setting is to be added or changed as part of this ADR.

## Provider research

### Current primary: DeepSeek

DeepSeek remains appropriate for text tasks already served by the application. The current integration uses LiteLLM chat completion. This branch contains no verified DeepSeek image-generation API adapter, so do not infer image input or image output capability from the existing chat integration.

### Candidate for a future image adapter: OpenAI Images API

Official documentation describes image generation and editing, including use of one or more input/reference images. This makes it a technically plausible candidate for a dedicated image adapter. It is not selected, configured, priced, or connected in PWA Studio. Before selection, compare current model availability, organization verification requirements, reference fidelity, data handling/retention, regional availability, latency, and actual per-image cost using a disposable test account and explicit budget.

### Other configured provider families

Anthropic and Ollama are represented in the current text-provider settings. Their presence in the text router is not evidence that the current app has image generation support for them. Evaluate them independently only if a concrete image-capable model and supported API contract are verified.

## Proposed request contract (not an active endpoint)

A future request should contain identifiers and intent, not arbitrary Storage paths:

```json
{
  "project_id": "uuid",
  "scene_id": "uuid",
  "prompt": "Scene description",
  "character_snapshot_ids": ["uuid"],
  "reference_asset_ids": ["uuid"],
  "output": {
    "format": "webp",
    "aspect_ratio": "16:9"
  },
  "idempotency_key": "uuid"
}
```

The server must derive the user identity from the verified Supabase bearer token. It must resolve every project, character snapshot and asset under that user. Client-supplied owner IDs, bucket names, Storage paths, public URLs and signed URLs must not be trusted.

## Required server-side controls

1. Enforce authentication and per-user rate/concurrency limits.
2. Verify project ownership and every reference asset's ownership/linkage.
3. Enforce a small per-scene reference count and strict byte/pixel limits.
4. Verify image signatures and decode safely; do not trust filename or browser MIME.
5. Reject unsupported/animated formats unless a reviewed decoder explicitly supports them.
6. Run content-safety checks appropriate to user-uploaded and generated images.
7. Require a user-facing confirmation naming provider, selected references, and expected charge/credit use before external transmission.
8. Keep credentials server-side; never expose service-role or provider keys to the browser.
9. Use private Storage and short-lived access only after ownership checks; do not persist signed URLs.
10. Persist job state and idempotency before provider submission; ambiguous outcomes must not be blindly resubmitted.
11. Record provider/model, reference asset IDs, scene/project IDs, token/image usage, cost source, and status; never log image bytes, bearer tokens, or provider secrets.
12. Keep local originals untouched on provider failure. Define provider-side retention/deletion disclosure before launch.
13. Deliver generated output through owner-scoped private storage and authenticated reads.
14. Test cross-account access, guessed UUIDs, expired sessions, MIME spoofing, malformed images, oversized payloads, retries, and cost accounting in isolated infrastructure.

## Continuity strategy

For each scene, send only references explicitly selected for that scene. Combine those images with:
- immutable identity traits;
- approved wardrobe for the scene;
- visual style and palette;
- camera/action/lighting instructions;
- explicit negative constraints.

Keep master character passports immutable during generation. Store the exact passport snapshot and reference asset IDs on the generation job so a retry or later review can reproduce the same intent. A model prompt can reduce drift but cannot guarantee pixel-identical identity across frames; evaluate outputs and offer user review/selection.

## Go-live gate

Do not expose an image-generation button until:
- a provider and model are deliberately selected;
- costs and spending limits are verified;
- a separate test environment and test credentials exist;
- ownership and upload validation tests pass;
- a private output-storage flow is tested;
- consent, safety, retention and deletion disclosures are in place;
- usage is measured without duplicate charges;
- browser and backend end-to-end tests pass.

Until then, the application must describe the feature as planning/continuity preparation, not image generation.
