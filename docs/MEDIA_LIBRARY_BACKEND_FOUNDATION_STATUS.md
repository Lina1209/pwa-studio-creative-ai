# Media Library Backend Foundation — Implementation Status

This change adds the first backend code foundation for the future Media Library:

- `backend/app/asset_schemas.py` defines strict Pydantic request/query/response contracts.
- `backend/tests/test_asset_schemas.py` covers filename path rejection, media-kind/MIME mismatch, MIME parameters, UUID validation, allow-listed attachment roles, pagination bounds, extra-field rejection and safe response shape. `backend/app/services/asset_access.py` adds fail-closed helpers that derive owner filters from the verified auth identity; `backend/tests/test_asset_access.py` covers UUID normalization, owner-scope override rejection and invalid identity handling.
- The upload-init model accepts only a conservative MIME allow-list. This is a validation of client-declared metadata, not proof of the actual uploaded file type.

## What is implemented

- Request models reject unknown fields, including client-supplied `owner_id`.
- Filenames cannot contain path components, control characters or empty/dot names.
- MIME values are normalized and must match the selected media family and the explicit allow-list.
- Project attachment uses a UUID asset reference and a constrained role/slot/position.
- List filters and page size are bounded.
- The safe response model contains no Storage path or signed URL field.

## What is not implemented

There are deliberately no `/api/assets` or project-asset routes yet, no upload signing, no bucket operations, no asset database writes, no download route, no physical deletion, and no project relationship persistence. The schemas are not wired into `main.py` and do not authorize access on their own.

## Why route implementation is gated

The source repository has overlapping migration definitions and a duplicate migration version. The live Supabase migration ledger, actual project/asset tables, RLS, grants, Storage bucket privacy and policies have not yet been inspected and reconciled. The current Mini Cinema project sync uses `public.projects`; a legacy `studio_projects` table also exists in migration source. These must not be treated as interchangeable without evidence.

Before adding routes, inspect the live schema and policy state using the existing read-only diagnostics, confirm the actual Storage upload/signing behavior, and then implement owner-scoped queries with server-derived user identity. Because server-side service credentials can bypass user RLS, every operation must explicitly constrain both asset and project ownership.

## Test execution status

The schema suite passed in GitHub Actions on commit `aed776af558b7217f966427870aebba9494948a1` (Backend tests, run 177). The owner-scope helper and its tests also passed in GitHub Actions on commit `beb2faf952769610563c215b164722470bdffd1f` (Backend tests, run 180). The subsequent documentation-only update on commit `3b63dd924239ff0876ff9c2c0771cd40a1cc4e0d` also passed (Backend tests, run 182). No production service, live database, Storage bucket, migration, or deployment was changed by this foundation.


## Owner-scope helper boundary

`backend/app/services/asset_access.py` is a pure helper and is not wired into API routes. It canonicalizes the UUID from the verified `StudioUser.user_id`, creates a PostgREST `owner_id=eq.<uuid>` filter, and rejects an extra parameter map that already contains `owner_id`. This is defense-in-depth only: every future route must still verify ownership of both the asset and the project, and the helper must be called only with the authenticated principal, never a client-supplied identifier. The helper does not establish live RLS, database schema, Storage policy, or upload-content validation.
