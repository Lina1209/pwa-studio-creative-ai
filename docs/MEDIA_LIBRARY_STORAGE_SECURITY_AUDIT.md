# Media Library and Storage — Source Security Audit

Status: **read-only source audit**. This document records repository evidence only. It does not claim that current live Supabase configuration was inspected.

## Executive result

The shared Media Library is **not implemented end to end**. The repository contains request schemas and owner-scope helper functions, but no asset metadata API, upload authorization/completion flow, signed-download authorization, project-asset persistence, or safe object-deletion worker. The Mini Cinema cloud sync stores project JSON in `public.projects`; that is separate from media binary storage.

Do not connect studio upload/download controls to these buckets or expose Storage operations as if a secure shared asset lifecycle already existed.

## Verified source facts

### 1. Application tables are two generations, not one interchangeable model

- `0001_initial_schema.sql` defines the legacy family `studio_projects(user_id)`, `studio_characters(user_id)`, `studio_scenes(user_id)`, and `studio_media(user_id, project_id, media_type, storage_path, metadata)`.
- `0005_cloud_projects_and_storage.sql` defines the newer `projects(owner_id)` table used by the current Mini Cinema cloud-sync implementation.
- `0001_initial_schema.sql` also defines account basics in `profiles`; `0009_user_profiles.sql` defines the separate community-facing `user_profiles` table.
- The legacy `studio_media` row shape includes a Storage path and JSON metadata, but source inspection alone does not prove that the object exists, is private, belongs to the same owner as its linked project, or is safe to return to a client.

These table families must not be silently merged or substituted. Any future asset service must explicitly identify the canonical project table and reconcile legacy rows before migration.

### 2. Storage migrations have a concrete policy collision

The repository contains two different files with version prefix `0005`:

- `0002_storage_and_moderation.sql` creates private `studio-media` and `studio-exports` buckets, with four user-owned object policies covering both buckets.
- `0005_cloud_projects_and_storage.sql` also configures `studio-media`, then drops and recreates the same four policy names for `studio-media` only.

If both files were applied in that order, the later file would replace the shared policy definitions and remove user-level policy coverage for `studio-exports`. This is a conditional source-derived result, not a claim about the live policy state.

The bucket definitions also disagree:
- `studio-media`: 250 MiB in migration 0002 versus 100 MiB in migration 0005.
- The MIME allow-lists differ: migration 0002 includes PDF but omits OGG/WebM audio and QuickTime video; migration 0005 includes OGG/WebM audio and QuickTime video but omits PDF.
- `studio-exports` is defined only in migration 0002, with a 1 GiB limit and a different MIME allow-list.

The effective live bucket limits, allow-lists, privacy and policies therefore cannot be inferred safely from the repository alone. Do not replay either historical migration to try to normalize the result.

### 3. Current Storage object policy model is not sufficient as a shared asset contract

Both migration files scope authenticated Storage object access by:
- bucket ID; and
- first folder component matching `auth.uid()::text`.

This is a useful per-user namespace boundary for direct authenticated Storage access, but it does not by itself establish:
- that an object has a corresponding verified asset metadata row;
- that the object is linked only to projects owned by the same user;
- that client-declared MIME, extension or size matches the actual binary;
- that object keys are opaque and server-generated;
- that uploaded content is safe to parse or render;
- that a shared asset remains available while another project references it;
- that a signed URL is short-lived, purpose-limited or revoked as intended.

The policies grant authenticated users object-level insert, update and delete in the configured namespace. No source-level quarantine/verification gate is attached to those direct object writes. Do not treat bucket MIME restrictions as binary-content validation.

### 4. Legacy media table and ownership constraints

The legacy `studio_media` table stores `user_id`, nullable `project_id`, `media_type`, `storage_path`, and free-form `metadata`. Its source migration enables RLS and scopes rows by `user_id`. The project link uses `ON DELETE SET NULL`, so deleting a project can leave a media row without a project association; it does not define a reusable asset relationship model.

The migration does not establish a composite database invariant proving that `studio_media.user_id` equals the linked `studio_projects.user_id`. Backend/service-role operations would need explicit checks, and any new relationship schema needs database-enforced owner equality.

### 5. Existing backend foundation is deliberately disconnected

Verified files:
- `backend/app/asset_schemas.py`: strict request/response models; rejects extra fields such as client `owner_id`, validates UUID/role, filename path components and declared MIME family.
- `backend/app/services/asset_access.py`: canonicalizes verified identity UUID and builds an explicit `owner_id=eq.<uuid>` PostgREST filter; rejects a caller-supplied owner filter.
- `backend/tests/test_asset_schemas.py` and `backend/tests/test_asset_access.py`: unit tests for those pure helpers and schemas.

These are not routes or authorization enforcement by themselves. The upload-init model trusts declared size and MIME as metadata; the source has no binary sniffing, checksum, content scanning, actual-size verification or upload-completion transition. No shared asset metadata table or project-asset relationship table is defined by the current source migrations.

### 6. Missing end-to-end capabilities confirmed by source review

Not implemented/verified:
- `/api/assets` list/detail routes;
- project asset list/attach/detach routes;
- upload-intent and upload-completion endpoints;
- server-generated object keys and narrowly scoped upload authorization;
- server-side binary type/size verification and quarantine;
- short-lived download URL issuance after owner authorization;
- object deletion with reference/job checks and retryable cleanup;
- per-owner quota, file-size enforcement at the API layer, concurrency and abuse controls;
- two-account Storage integration tests.

The current Mini Cinema sync tests cover project-record owner/auth-generation races. They do not exercise Storage object policies or binary media.

## Risk register

| Severity | Finding | Required treatment |
|---|---|---|
| Critical blocker | No end-to-end asset authorization/lifecycle API exists | Do not enable shared media upload/download using an assumed API |
| High | Duplicate migration prefix 0005 and overlapping policy names | Reconcile live migration history and exact policies before any SQL |
| High | Conflicting bucket limits/MIME allow-lists | Inspect live bucket configuration; design one forward-only correction only if evidence requires it |
| High | Direct authenticated object writes have no verified-content lifecycle gate | Future upload flow must quarantine and verify before an asset becomes reusable |
| High | Legacy media/project owner equality is not a composite DB invariant | Validate both owners server-side and enforce relationship ownership in the database |
| Medium | Legacy media rows can be orphaned from a project by `ON DELETE SET NULL` | Inventory and define migration/retention policy; never delete originals merely because a project is removed |
| Medium | MIME/size values in the current schema are client-declared only | Treat as hints; verify bytes and actual object metadata server-side |

## Required live read-only reconciliation

The existing `supabase/diagnostics/inspect_project_asset_security.sql` and `supabase/diagnostics/inspect_cloud_storage.sql` are SELECT-only starting points. Before designing routes or a migration, collect:

1. The actual migration ledger and how the two historical 0005 files were handled.
2. Exact live columns, nullability, constraints, indexes, grants and RLS for both `projects` and legacy `studio_*` tables, plus any existing asset tables.
3. Exact live `storage.buckets` configuration for both buckets, including privacy, size limits and MIME allow-lists.
4. Every `storage.objects` policy, including role, command, USING and WITH CHECK expressions.
5. Existing storage metadata/owner conventions, without exporting object names or private content.
6. A disposable two-account integration test of list/read/upload/update/delete denial across accounts A and B.

The existing diagnostics are metadata-oriented; they do not prove actual two-account behavior. Use only disposable test accounts and harmless synthetic files for runtime tests. Do not use the owner's personal account or private media for adversarial tests.

## Safe implementation order after reconciliation

1. Confirm the canonical project table and live migration history.
2. Design a new asset metadata table and project-asset relation with database-enforced owner invariants; do not guess the schema.
3. Implement owner-scoped metadata list/detail/attach/detach first, using verified auth identity and explicit owner filters for every service-role query.
4. Implement upload intent, server-generated opaque keys, strict size limits and a quarantine state.
5. Verify actual bytes/content type/size/checksum and apply safe media parsing/scanning before status becomes `ready`.
6. Add short-lived download authorization and safe response projections; never persist signed URLs in project JSON.
7. Add reference-aware, retryable deletion. Detaching a project link must never delete a shared original.
8. Run unit, concurrency, account-switch and disposable two-account integration tests.
9. Connect Mini Cinema first, then extend the same verified asset contract to image, music, voice, video and audio studios.

## Release boundary / non-actions

- No live Supabase query was run as part of this source review.
- No SQL, migration, RLS policy, grant, bucket or object was changed.
- No user media was read, uploaded, downloaded, signed or deleted.
- No upload, download, public sharing, billing, provider generation or credit deduction was triggered.
- PR #4 remains a draft and production `main` remains untouched.
- Passing mocked/unit CI does not prove live Storage isolation or binary safety.


## Follow-up review — 2026-11-24

### Additional contract-level observations

- The upload-init schema validates a positive declared `size_bytes`, but does not impose a maximum size. This is not currently an exploitable upload route because no upload-init endpoint exists; it is a required policy decision before one is implemented. The maximum must be aligned with a single reconciled bucket/API policy and enforced against actual uploaded bytes, not just the client declaration.
- MIME allow-lists are deliberately narrow and exclude active web content such as SVG and HTML. Keep that restriction unless a separate safe-rendering and sanitization design is reviewed.
- The owner-scope helper rejects a caller-supplied `owner_id` filter, but it is only a pure helper. It must be used on every service-role query and paired with explicit asset-owner and project-owner checks when routes are eventually implemented.
- The current safe response model omits raw Storage paths and signed URLs. Future download authorization should return only short-lived, purpose-scoped URLs after an owner check; never persist them in project JSON, logs, or telemetry.
- No shared asset routes or storage operations were discovered in the current application route tree. Existing schema/helper tests are not evidence of end-to-end upload, download, or cross-account isolation.

### Release gate reaffirmed

Storage object access, actual MIME/size verification, quarantine, metadata persistence, reference-aware deletion, and two-account A/B integration tests remain unimplemented or unverified. Do not connect studio upload controls to the buckets until the live migration ledger, bucket settings, and policies are reconciled. No production SQL, Storage operation, upload, download, deletion, or deployment was performed during this follow-up.


### Follow-up: strict declared byte-count typing (2026-11-24)

- The future upload-intent schema now requires `size_bytes` to be a positive strict integer. Booleans, fractional values and numeric strings are rejected instead of being coerced into byte counts.
- Added parameterized regression coverage for invalid/coercible values.
- This is input-shape validation only. It does not establish an upload-size ceiling or verify actual object bytes. A maximum must be chosen only after reconciling the conflicting live bucket/API limits; actual uploaded size and content type must still be independently verified by the server.
- No upload routes were added. No live Storage settings or objects were accessed or changed.
