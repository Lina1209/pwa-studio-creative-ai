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


## Local v1 → cloud payload mapping (design only; not wired)

The current browser record shape was audited in `app.js`:
- top-level: `id` (browser UUID), `name`, `description`, `kind`, `representation`, `voice`, `passport` (`face/body/wardrobe/palette`), `referenceImages[]` (`id/name/type`), `createdAt`, `updatedAt`.
- binary image Blobs are in IndexedDB database `pwa-studio-character-library-v1`, object store `images`, keyed by reference id and tagged with ownerId.
- records are in localStorage key `pwa-studio-character-library-v1:<auth user UUID>` (or `:guest`).

Proposed metadata mapping:
- `name` → API `name`.
- `description` → API `description` (the API limit must be aligned with existing local 5,000-character limit before import is enabled).
- `kind`, `representation`, `voice`, `passport`, and reference image descriptors → API `reference_data`.
- `createdAt` stays local provenance unless a reviewed server schema explicitly supports it.
- local `id` must be preserved in a separate explicit mapping record; never assume a browser UUID is a cloud ID.
- image blobs are uploaded only through the authenticated server upload route after cloud character creation; no Blob/base64 data is placed in `reference_data`.

A safe importer still needs durable idempotency across interrupted requests, an explicit local↔cloud ID mapping, per-image upload state, a read-back verification step, and a non-destructive backup/rollback procedure. Current API POST does not yet provide a durable idempotency key or caller-selected ID; retries can create duplicates. Therefore do not implement automatic retries or frontend import yet. Guest records remain local-only. Existing records and image blobs must never be deleted as part of import.
