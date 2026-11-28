# PWA Studio security review — reference assets and generation boundary

**Review date:** 2026-11-27  
**Scope:** feature branch feature/character-library-foundation; source review only.  
**Status:** findings recorded; no production access, no migration execution, no provider calls.

## Executive result

The current design keeps character references local-first and sends text-only continuity information to /api/chat. The inspected backend has no image/video generation route. The reference validator now checks file signatures, declared MIME consistency, per-file and aggregate byte limits, then fully decodes PNG/JPEG/WebP with pinned Pillow 13.0.0. It rejects corrupt/truncated files, animated images, dimensions above 8192px, and images above 16 megapixels. The draft character schema uses owner-scoped RLS and a composite owner-safe character/media foreign key.

This is useful groundwork, but it is not yet a secure external image-upload pipeline. Do not tell users their reference images are sent to an AI model. Do not activate cloud backup or provider handoff based only on these source checks.

## Verified source facts

1. backend/app/main.py exposes the current chat and account/community APIs; the inspected route declarations include no generation/image/video endpoint.
2. app.js contains references to /api/chat and the studio-media identifier, but the reviewed branch has no /api/generate, generation_jobs, uploadReference, or signed-URL handoff string in that file.
3. REFERENCE_GENERATION_SAFETY.md explicitly describes a text-only continuity brief. It states that browser image blobs are not sent to /api/chat.
4. image_reference_validation.py currently performs byte-count and signature/MIME checks for PNG, JPEG, and WebP. It does not decode image pixels or verify full file integrity.
5. The reference batch validator now rejects empty lists, more than six references, non-ValidatedReference entries, inconsistent size metadata, and batches above 24 MiB.
6. Migration 0012's draft has RLS enabled on characters and media_assets, authenticated owner-only policies, and a composite FK (character_id, owner_id) -> characters(id, owner_id). This protects relational association ownership when the migration is correctly applied.
7. Migration 0012 does not itself create or prove the private Storage bucket's object policies. The separate preflight checks bucket/policy conditions and must be run only in a disposable test project.
8. The backend now pins Pillow 13.0.0 (Python 3.12 runtime) and the validator performs full decode with 8192px per-axis and 16-megapixel limits, one frame maximum, and decompression-bomb warnings treated as errors. This is bounded validation in the API process, not a separate sandbox or OS-level memory/time isolation.

## Findings and required action

### SEC-REF-01 — Signature validation is not image decoding (high, blocks external upload)

A file can begin with a valid PNG/JPEG/WebP signature yet be truncated, malformed, or crafted to stress a decoder. Signature sniffing alone does not establish that the complete image is safe to decode.

Required before any external handoff:
- Choose and pin a maintained decoder dependency after dependency/security review.
- Decode in a bounded, isolated execution path; enforce maximum width, height, total pixels, frame count, and decoded-memory budget.
- Reject truncated/corrupt files and decompression bombs; normalize accepted images to a safe raster format before provider transmission.
- Keep raw originals private and never run arbitrary file parsing in a privileged process without resource limits.
- Add tests for truncated files, malformed chunks, huge dimensions, multi-frame inputs, and decoder exceptions.

### SEC-REF-02 — Ownership must be checked before bytes are read (critical, blocks cloud/provider flow)

The validator deliberately does not perform ownership checks. Every future API must:
- validate the Supabase JWT server-side;
- derive owner ID from the verified token, never request JSON;
- load project, character snapshot, and every selected media asset by ID with owner predicates;
- verify asset-character and asset-project associations where applicable;
- only then read the private object or issue a short-lived signed URL;
- return a generic not-found/forbidden response without leaking whether another user's UUID exists.

### SEC-REF-03 — Private Storage policy remains an independent gate (critical, blocks cloud/provider flow)

A private bucket name or a database RLS policy does not secure Storage objects by itself. Before enabling backup:
- verify the bucket is private;
- inspect every storage.objects policy and grant;
- require the authenticated owner path convention and a server-validated object association;
- test read, list, insert, update, and delete isolation for two users;
- ensure service-role access is backend-only and no signed URL is persisted in metadata or logs.

### SEC-REF-04 — Upload and object lifecycle need transactional compensation (high)

Database rows and Storage object writes do not share one transaction. Design an explicit state machine for pending upload, verified object, committed media row, failed upload, and orphan cleanup. Use unique object keys and idempotency. A failed DB commit after upload must leave a private orphan eligible for safe cleanup; a failed upload must not create a usable media row.

### SEC-REF-05 — Reference validation bounds need decoder-aware tests (high)

The validator enforces batch object/type and size metadata, plus per-file/aggregate bytes and decoded dimensions/pixels/frame count. Keep all limits server-enforced even if the browser already enforces them. Isolation and normalization remain outstanding.

### SEC-REF-06 — Generation and chat boundaries must remain separate (critical)

The inspected code has no active generation endpoint. Do not overload /api/chat with image bytes, data URLs, arbitrary Storage paths, or signed URLs. A future dedicated endpoint must require explicit user confirmation naming the provider and exact selected references, then create a durable job and provider-attempt record before any external call.

## Minimum isolated acceptance matrix

- User A and User B cannot read, list, sign, upload, associate, replace, or delete one another's references.
- Forged owner IDs, project IDs, character IDs, and Storage paths are ignored/rejected.
- A user cannot attach an asset from another project/character unless an explicit product rule allows it and ownership is still verified.
- Private bucket access is denied for anonymous users and cross-owner paths.
- MIME mismatch, extension mismatch, truncated/corrupt images, oversized bytes, excessive dimensions/pixels, malformed metadata, and excessive batches are rejected.
- Upload succeeded / DB commit failed and DB row pending / upload failed both recover safely without exposing orphan objects.
- Only the exact references selected for a scene are sent after explicit confirmation.
- Text-only /api/chat remains free of image bytes and signed URLs.
- Provider timeout/unknown acceptance enters reconciliation; it never triggers a blind second billable request.
- Logs contain no prompts, image bytes, signed URLs, bearer tokens, or provider credentials.

## Current activation decision

**NO-GO for cloud backup activation, external image transmission, or generation worker integration** until SEC-REF-01 through SEC-REF-04 are implemented and the two-user Storage/API tests plus decoder tests pass in an isolated Supabase project.

This review is documentation and source-level hardening only. It does not apply migrations, change production configuration, enable any provider, or run paid requests.
