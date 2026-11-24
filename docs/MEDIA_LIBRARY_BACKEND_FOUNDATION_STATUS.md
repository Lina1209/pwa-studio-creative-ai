# Media Library Backend Foundation — Implementation Status

This change adds the first backend code foundation for the future Media Library:

- `backend/app/schemas/assets.py` defines strict Pydantic request/query/response contracts.
- `backend/tests/test_asset_schemas.py` covers filename path rejection, media-kind/MIME mismatch, MIME parameters, UUID validation, allow-listed attachment roles, pagination bounds, extra-field rejection and safe response shape.
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

The tests have been added to the repository but have not yet been executed in this environment. CI must run against the latest branch head before treating them as passing. No production service, live database, Storage bucket, migration, or deployment was changed by this foundation.
