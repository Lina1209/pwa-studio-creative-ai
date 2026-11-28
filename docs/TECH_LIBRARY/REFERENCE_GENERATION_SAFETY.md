# Safe character-reference handoff to generation

Status: preparation contract only. This document does not enable image uploads to an AI provider.

## Current behavior
- Mini Movie Studio stores a compact character/location passport snapshot with the project.
- A creator can select reference IDs and assign them to scene numbers.
- Studio AI prompts now receive a bounded text-only continuity brief: passport traits, scene assignments, and selected reference names.
- The browser does **not** read image blobs from IndexedDB for the `/api/chat` request. No image bytes, data URLs, Storage paths, or signed URLs are included.
- The current `/api/chat` call is text JSON. It is not an image-generation endpoint and must not be treated as one.
- Selected reference names help a human and the text model understand the intended visual anchors; they do not prove the model has seen the images.

## Required architecture before real image generation
1. Add a dedicated authenticated generation endpoint, separate from `/api/chat`.
2. Define a provider-neutral request contract with project ID, scene ID, prompt, approved character snapshot IDs, and explicit reference asset IDs.
3. Resolve asset IDs server-side. Verify the current authenticated owner for the project, character, and every asset. Never trust client-supplied owner IDs or arbitrary Storage paths.
4. Keep the Storage bucket private. Fetch reference files server-side or issue short-lived signed URLs only after owner checks; never persist signed URLs.
5. Validate file type by inspecting file content, not only filename/MIME; enforce byte limits, image dimensions, count limits, and safe decoding. Reject unsupported formats and malformed files.
6. Add explicit user confirmation before any image is transmitted to an external provider. Show which images and which provider will receive them.
7. Send only the selected references for the requested scene. Do not upload every library image by default.
8. Record provider, model, asset IDs, scene ID, request timestamp, and usage/cost metadata without storing unnecessary image copies or secrets in logs.
9. Handle provider failures without deleting local originals. Use bounded retries and idempotency keys to prevent duplicate charges.
10. Keep generation opt-in and private by default. Provide a clear cancel path and retention/deletion policy for provider-side copies.

## Scene continuity contract
For each generated scene, keep separate:
- **Identity lock:** face, hair, eyes, silhouette, distinguishing marks.
- **Wardrobe lock:** outfit and accessories; changes require scene-specific approval.
- **Style lock:** palette, rendering style, 2D/3D intent.
- **Reference assets:** explicit asset IDs chosen by the creator for this scene.
- **Scene action:** pose, expression, movement, camera, lighting, environment.
- **Negative constraints:** traits that must not drift or be invented.

A scene-specific reference selection overrides a character's general reference selection only for that scene. It must not mutate the master character passport. Project versions must preserve the exact snapshot and reference IDs used.

## Acceptance tests before enabling provider handoff
- User A can submit only assets owned by A and linked to A's project/character.
- User B cannot read, sign, or submit A's reference assets, including by guessing UUIDs.
- A guest cannot call authenticated generation endpoints.
- The provider receives only the scene's selected assets, not unrelated library files.
- An explicit confirmation is required before external transmission.
- MIME spoofing, oversized images, corrupt files, too many references, and expired sessions are rejected safely.
- Provider failure leaves local files and project snapshots intact.
- Usage is recorded once per idempotency key; retries do not double-charge.
- A project version restored later reproduces the same prompt snapshot and selected reference IDs.

## Not implemented
No real image upload, image-to-video provider adapter, signed-URL flow, image moderation pipeline, provider-side deletion, scene render endpoint, or end-to-end security test exists yet. Do not tell users that references have been sent to a model until those pieces are implemented and tested.
