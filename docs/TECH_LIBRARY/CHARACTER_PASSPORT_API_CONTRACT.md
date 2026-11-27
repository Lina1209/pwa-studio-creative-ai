# Character passport API contract (feature branch)

Status: implementation foundation; do not deploy or apply migrations.

## Endpoints planned
- `GET /api/characters`: list at most 100 records filtered by the verified JWT subject.
- `POST /api/characters`: create a passport. The server supplies `owner_id`; client-supplied ownership fields are forbidden by the request schema.
- `GET /api/characters/{id}`: read only a row matching both character ID and authenticated owner.
- `PATCH /api/characters/{id}`: update only name, description and reference_data, again filtered by both identifiers.
- No DELETE endpoint is provided. Character removal must use the existing cleanup/outbox lifecycle.

## Data contract
The existing migration 0012 schema has `id`, `owner_id`, `name`, `description`, `avatar_url`, `reference_data`, and `created_at`. The API intentionally does not accept avatar URLs or storage paths and returns only `id`, `name`, `description`, `reference_data`, and `created_at`. Image blobs remain in IndexedDB until an explicit, verified backup flow exists.

`reference_data` must be a JSON object, max 24 KiB serialized, max depth 6, max 80 keys per object, max 100 items per array, and max 4,000 characters per string. Name is 1–120 characters; description max 2,000 characters. The database service credential is server-only.

## Security requirements
- All requests require a valid authenticated session; guests remain local-only.
- Every read/update/list query includes both `id` (where applicable) and the verified `owner_id`.
- Missing and foreign-owned records share the same 404 response.
- Request models reject unknown fields, including owner_id and storage_path.
- No browser-supplied bucket, object key, signed URL, or owner ID is trusted.
- RLS remains defense in depth; server filters are mandatory.
- No deletion; use cleanup intent and the fenced media cleanup worker.

## Integration gate
The UI must not call these endpoints until route registration, automated tests, disposable Supabase tests, and a local-to-cloud mapping/import design are complete. Never delete local IndexedDB records as part of a failed or partial cloud operation.
