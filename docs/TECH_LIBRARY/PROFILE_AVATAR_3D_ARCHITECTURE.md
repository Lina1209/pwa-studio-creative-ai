# Profile avatar 3D architecture and readiness contract

**Status:** design only; no 3D runtime, model assets, or active 3D picker.  
**Branch:** `feature/character-library-foundation`  
**Date:** 27 November 2026

## Current repository evidence

The application is a static frontend with `index.html`, `app.js`, and `styles.css`; there is no root package manifest, no Three.js/Babylon.js dependency declaration, no `.glb`/`.gltf` assets, and no model-viewer component in the repository tree. The current avatar catalogue contains nine local 2D SVG assets. The profile API deliberately accepts only the `2d` representation.

Therefore the 3D tab must remain disabled. Do not substitute a perspective SVG, emoji, CSS effect, or rendered 2D portrait and call it a 3D model.

## User-facing product model

- Keep profile avatar identity separate from Character Library records and film-project cast snapshots.
- Provide a real 3D catalogue as a separate representation, not as a forced conversion of existing 2D choices.
- Keep a user's current 2D avatar until they explicitly preview and apply a supported 3D choice.
- Katty/Katarina should retain the same recognizable identity across approved 2D and 3D assets, but each representation is a separately curated asset.
- Preserve a clear 2D fallback for devices that cannot render 3D, reduced-motion preferences, renderer failures, and accessibility tools.
- Never silently switch a user's representation or trigger a paid generation request.

## Proposed asset manifest

A future versioned catalogue entry should contain only validated, non-secret metadata, for example:

- stable `catalog_id` and catalogue version;
- `representation: "3d"`;
- human-readable name and category;
- approved model asset identifier and immutable revision;
- media type restricted to glTF binary (`model/gltf-binary`) or approved glTF JSON with a controlled resource policy;
- declared byte size, SHA-256 digest, and bounded dimensions/animation metadata;
- thumbnail/fallback 2D catalogue ID;
- licensing/attribution status and moderation approval state.

Do not accept arbitrary remote model URLs or embedded external resource URLs from clients. Prefer same-origin, versioned, immutable assets after security and licensing review.

## Model validation and safety gates

Before any model can enter the public catalogue:

1. Validate file signature and parse the glTF structure; do not trust extension or client MIME alone.
2. Reject external network references, scripts, HTML, executable payloads, and unapproved extensions.
3. Enforce explicit caps for total bytes, mesh count, vertices, materials, texture count, texture dimensions, animation clips, and decoded memory.
4. Decode textures through a constrained pipeline; reject oversized or malformed images.
5. Scan and moderate the visible model and thumbnail, and verify rights to distribute the asset.
6. Store approved assets under immutable, controlled paths; never expose private upload storage paths.
7. Verify digest and metadata at ingestion and serve with safe content types and cache policy.

Initial caps must be chosen from measured mobile-device tests, not guessed in the client. Uploads/custom models are a separate feature and require explicit user consent, owner isolation, quota, moderation, and deletion lifecycle.

## Renderer decision gate

Do not add a renderer dependency until a small proof of concept demonstrates:

- acceptable first-load and memory use on target Android devices;
- lazy loading only after a user opens the 3D tab or previews a model;
- no renderer initialization on normal account/profile page load;
- bounded frame rate and pause when hidden/off-screen;
- reduced-motion support and a static thumbnail fallback;
- keyboard-operable controls, labelled actions, and a non-3D equivalent;
- safe disposal of GPU resources when closing preview or changing account;
- deterministic behavior when WebGL is unavailable or context is lost.

Compare maintained renderer options only at that point. Select one deliberately, pin its version, review bundle size/license/security, and add tests. No provider or paid service is required for locally hosted approved models.

## Persistence/API compatibility

- Keep `avatar_catalog_id` and `avatar_representation` as the profile's logical selection.
- Server allowlist must contain only published catalogue entries; the representation must match that entry.
- Do not accept arbitrary asset paths, URLs, owner IDs, or storage keys from the browser.
- A future API change from 2D-only to 2D/3D must be additive and separately tested; until then, server rejection of `3d` is intentional.
- Guest selection remains browser-local and isolated from authenticated profiles.
- Account-switch fencing must cover model metadata, thumbnail loads, and preview lifecycle, not only save requests.
- If a model fails validation or loading, preserve the previous saved avatar and show its safe fallback.

## Acceptance criteria before enabling the 3D tab

- At least one approved, licensed, real 3D model exists in the controlled catalogue.
- The same identity has a reviewed 2D fallback; Katty's 2D/3D identity consistency is visually approved.
- Renderer is pinned, lazy-loaded, security-reviewed, and tested on supported mobile devices.
- API catalog allowlist and additive persistence behavior pass owner-isolation and account-switch tests.
- Tests cover malformed models, external resource rejection, resource caps, failed loads, WebGL absence/context loss, reduced motion, keyboard accessibility, and fallback preservation.
- UI copy clearly distinguishes real 3D models from 2D images.
- CI passes on the feature branch.

## Out of scope until separately approved

No production migration, merge, deployment, live database operation, external provider, paid generation, automatic conversion of 2D portraits, custom model upload, or automatic replacement of a user's selected avatar.
