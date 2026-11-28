# Character passport API contract (feature branch)

Status: implementation foundation; do not deploy or apply migrations.

## Endpoints planned
- `GET /api/characters`: list at most 100 records filtered by the verified JWT subject.
- `POST /api/characters`: create or recover a passport idempotently. The client supplies its existing local UUID as `source_local_id`; the server supplies `owner_id` and the cloud UUID. Repeating the same request returns the same cloud row; reusing a local UUID with changed content returns 409.
- `GET /api/characters/{id}`: read only a row matching both character ID and authenticated owner.
- `PATCH /api/characters/{id}`: update only name, description and reference_data, again filtered by both identifiers.
- No DELETE endpoint is provided. Character removal must use the existing cleanup/outbox lifecycle.

## Data contract
The existing migration 0012 schema has `id`, `owner_id`, `name`, `description`, `avatar_url`, `reference_data`, and `created_at`; migration 0020 adds nullable `source_local_id` with a unique owner-scoped constraint. The API intentionally does not accept avatar URLs or storage paths and returns `id`, `source_local_id`, `name`, `description`, `reference_data`, and `created_at` (never `owner_id`). Image blobs remain in IndexedDB until an explicit, verified backup flow exists.

`reference_data` must be a JSON object, max 24 KiB serialized, max depth 6, max 80 keys per object, max 100 items per array, and max 4,000 characters per string. Name is 1–120 characters; description max 5,000 characters. The database service credential is server-only.

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
- `description` → API `description` (the API limit is aligned with the existing local 5,000-character limit).
- `kind`, `representation`, `voice`, `passport`, and reference image descriptors → API `reference_data`.
- `createdAt` stays local provenance unless a reviewed server schema explicitly supports it.
- local `id` is sent as `source_local_id`; the server generates a separate cloud `id`. The API response returns both IDs so the browser can persist an explicit local↔cloud mapping.
- image blobs are uploaded only through the authenticated server upload route after cloud character creation; no Blob/base64 data is placed in `reference_data`.

The durable owner-scoped idempotency primitive now protects metadata creation across interrupted/retried requests. A safe importer still needs per-image upload state, read-back verification for every uploaded object, and a non-destructive backup/rollback procedure. Therefore do not implement frontend import yet. Guest records remain local-only. Existing records and image blobs must never be deleted as part of import.


## Durable local-to-cloud identity (migration 0020 draft)

The importer must send the browser record's existing UUID as `source_local_id`. A unique `(owner_id, source_local_id)` constraint makes the mapping private to one account while allowing different accounts to use the same local UUID. A service-role-only `pwa_create_character_idempotent` RPC inserts once and returns the existing row on an exact replay. If the same owner/local UUID is replayed with different name, description, or passport JSON, the RPC raises a conflict; it never silently overwrites the cloud passport.

The browser receives both `id` (cloud identity) and `source_local_id` (local identity) and can persist this mapping locally. The local UUID is not accepted as the cloud primary key. Authenticated browser roles lose direct INSERT/UPDATE/DELETE privileges on `public.characters`; writes must use the authenticated API. Migration 0020 and its SQL behavior test are draft-only and are intended for the disposable PostgreSQL CI harness, never production.


## Per-image upload progress and read-back

`GET /api/characters/{character_id}/references` lists only the caller’s assets for the specified owned character. It returns asset ID, display metadata, dimensions, creation time, and lifecycle status; it never returns Storage paths, bucket, owner ID, internal metadata, or signed URLs. The result is private/no-store. The importer must map each local reference to the returned asset ID and treat only `ready` as independently verified. `object_uploaded` remains pending until the background verifier completes. For stronger read-back, download the ready asset through the authenticated `/api/media/{asset_id}/content` proxy and compare its bytes to the local reference SHA-256 before marking the local backup record verified.
