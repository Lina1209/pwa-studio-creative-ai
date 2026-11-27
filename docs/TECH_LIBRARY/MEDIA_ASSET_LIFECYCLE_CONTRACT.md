# PWA Studio — private media asset lifecycle contract

**Status:** design/security contract only; no upload, signed-URL, delete, or cleanup API is active.
**Scope:** future character references, project media, and private exports in Supabase Storage.
**Activation:** NO-GO until the two-account integration matrix and decoder validation pass.

## 1. Non-negotiable ownership boundary

- Authenticate every request with a server-verified Supabase JWT.
- Derive `owner_id` only from the verified JWT subject. Ignore/reject owner IDs supplied in JSON, query parameters, headers, filenames, or Storage paths.
- Treat every client-supplied project, character, and media UUID as an untrusted selector.
- Before reading, signing, replacing, moving, or deleting object bytes, load the relevant database rows with both `id = requested_id` and `owner_id = authenticated_owner`. Return the same generic 404 for absent and foreign-owned records.
- Verify composite ownership links: media-to-project and media-to-character. A media asset cannot be attached to a foreign project or character even if the caller knows its UUID.
- Keep buckets private. Never create public URLs or persist signed URLs in rows, local metadata, logs, audit events, or notifications.
- Do not accept arbitrary `storage_path` from the browser for read/sign/delete operations. Resolve the immutable path from the owner's database row.
- Service-role credentials stay server-side. A privileged Storage call is permitted only after the explicit ownership checks above.

## 2. Object key contract

Use server-generated, non-reusable object keys; never derive the key from a user filename:

`<owner-uuid>/<resource-kind>/<resource-uuid>/<random-object-uuid>.<validated-extension>`

Allowed resource kinds are a closed server-side set (for example `characters`, `projects`, `exports`). Validate UUIDs as UUIDs. Reject empty path segments, dot segments, backslashes, encoded separators, leading slashes, and any path whose first segment differs from the authenticated owner. Preserve the original filename only as display metadata after sanitization.

A replacement creates a new object key and updates the database pointer only after the new object is verified. Do not overwrite a previous object's bytes in place: immutable keys make rollback, cache behavior, and cleanup safer.

## 3. Upload state machine and compensation

States:

1. `pending_upload` — server has reserved a unique key and inserted a pending row; not readable/signable by clients.
2. `object_uploaded` — Storage upload succeeded; server verifies object existence, size, bucket, owner path, and expected content metadata.
3. `ready` — database row is committed as usable; only this state can be listed, read, or signed.
4. `upload_failed` — upload/verification failed; no usable media row is exposed.
5. `cleanup_pending` — an unreferenced object or superseded version awaits deletion.
6. `deleted` — object deletion and metadata tombstone are complete.

Storage and Postgres do not share a transaction. Use an idempotency key and unique object key for each upload attempt. If upload fails, mark the pending row failed. If upload succeeds but the DB commit fails, record/recover the object as an orphan for cleanup; do not return a usable asset. If metadata commit succeeds but later verification fails, transition to cleanup and prevent signing immediately.

Cleanup must be owner-scoped, idempotent, bounded, and auditable. A cleanup worker must re-check that no ready media row references the exact bucket/path before deleting. Never delete based solely on a client-supplied path. Retry transient failures; retain a tombstone and alert on persistent failures. Do not let a cleanup failure expose data or make the asset usable.

## 4. Read and signed URL contract

- Read/sign endpoints accept a media asset UUID, not a bucket/path or URL.
- Query the row by `id`, authenticated `owner_id`, and `status = 'ready'`; verify its linked project/character owner and expected bucket.
- Generate a short-lived signed URL only after those checks. Use the shortest practical expiry (initial target: 60 seconds) and do not log the URL.
- Signed URLs are bearer capabilities: anyone possessing one may access the object until expiry. They must not be placed in public profiles, community feeds, analytics, error messages, or durable metadata.
- For sensitive originals, prefer authenticated proxy streaming over signed URLs where practical.
- A signed URL already issued cannot reliably be revoked by deleting the database row alone. For urgent revocation, delete/move the object or use a proxy that checks ownership on every request.
- Do not expose whether another user's asset UUID exists; return a uniform not-found response.

## 5. Replace, move, and delete

- Replace: upload and verify a new immutable object, atomically switch the owner's media row to the new path, then mark the old object `cleanup_pending`. If pointer update fails, retain the old ready object and clean up the new orphan.
- Move/associate: do not move Storage objects merely to change a project/character association. Validate ownership and composite foreign keys first; update only the association. If a physical move is unavoidable, use copy → verify → DB pointer switch → old-object cleanup.
- Delete: verify row ownership; mark unavailable/tombstoned first; remove object using the database-stored key; then finalize deletion. A failed object delete remains `cleanup_pending`, never reverts to publicly readable.
- Deleting a project may set `project_id = NULL` on media owned by the same user, but must not null `owner_id`. Character deletion behavior must be explicitly chosen; current composite FK uses RESTRICT while references exist.
- Repeated requests must be idempotent. A duplicate delete must not delete a different object's bytes or return another user's state.

## 6. File validation before Storage or provider use

- Enforce request body, per-file, and aggregate byte limits server-side before buffering unbounded content.
- Verify actual file signature and MIME; extension is metadata only.
- The current branch pins Pillow 13.0.0 and fully decodes PNG/JPEG/WebP; it rejects corrupt/truncated inputs, multi-frame images, dimensions above 8192px per axis, and images above 16 megapixels. Treat this as in-process validation, not an OS sandbox.
- Before accepting untrusted uploads at scale, move decoding to a separately resource-limited worker/process and add fuzzing/adversarial corpus coverage.
- Normalize provider-bound images to a safe raster format. Keep originals private.
- Do not send reference bytes to /api/chat. No provider transfer is permitted until the user explicitly confirms the provider and exact selected references.

## 7. Required audit and privacy

Audit only opaque asset IDs, owner IDs, action, outcome, and timestamps where necessary. Never log bearer tokens, service-role keys, signed URLs, file bytes, raw prompts, or sensitive EXIF/location metadata. Strip EXIF from normalized derivatives unless the product has an explicit, reviewed reason to retain it.

## 8. Acceptance tests before activation

Use two disposable Auth accounts A and B, and exercise both buckets separately:

- A can upload, list, read/sign, replace, and delete A's own ready assets.
- B cannot read/list/sign/overwrite/move/delete A's object, even when B knows A's media UUID, project UUID, character UUID, or exact object path.
- Anonymous requests cannot list or read private objects.
- A cannot create a database row that points to B's project/character or an arbitrary path.
- Owner IDs in request bodies and paths cannot override the verified JWT subject.
- Pending/failed/cleanup-pending assets cannot be listed or signed.
- Upload succeeds + DB commit fails: object remains private and is cleaned up safely.
- Upload fails: no ready row exists and no signed URL is issued.
- Replacement failure preserves the previous ready version.
- Delete failure leaves an unavailable tombstone and safe retry.
- Expired signed URLs stop working; signed URLs are never persisted or logged.
- Corrupt, truncated, huge-dimension, multi-frame, and decompression-bomb image inputs are rejected.

## 9. Current implementation boundary

At this revision there is no backend media upload/read/sign/replace/delete route, no Storage lifecycle service, and no cleanup worker. `image_reference_validation.py` now performs full bounded Pillow decoding, but does not normalize images, strip EXIF, or isolate decoding in a separate OS-limited worker. Migration 0017 is a draft schema hardening change, not a deployed policy. This contract must not be interpreted as an implemented upload or cloud-backup feature.

## 10. Backend guard primitives added (not an endpoint)

`backend/app/services/media_access.py` now provides small reusable guards for the future route layer:

- canonical UUID parsing for untrusted resource selectors;
- uniform 404 behavior for absent and foreign-owned rows;
- same-owner validation for project/character associations;
- server-structured immutable object-key construction using an allowlisted resource kind and image extension;
- allowlisting of the two private bucket names.

These helpers do not query Supabase, upload/download bytes, or create signed URLs. A future service must still query each row using both the requested ID and the authenticated JWT subject before passing it to the guards. The helper's unit tests are authored in `backend/tests/test_media_access.py`; they have not been executed in this workflow.

## 11. Owner-filtered metadata repository added (not a route)

`backend/app/services/media_repository.py` adds a server-only metadata lookup for a media asset. It filters the media row by both canonical asset UUID and the authenticated owner UUID, then independently checks any linked project and character using the same owner filter. Missing and foreign-linked resources are intentionally indistinguishable (404).

The repository uses the existing server-side Supabase REST pattern and service-role credential; that credential is never returned or accepted from a caller. Table names are fixed in code, and the function accepts no bucket, object path, or signed URL from the client.

This is a repository primitive only. No FastAPI route, upload, download, Storage operation, signed URL, or deletion endpoint has been added. The returned metadata includes `storage_path` for trusted internal follow-up only; a future route must not serialize it to the browser. The new mocked unit tests are in `backend/tests/test_media_repository.py`; they have not been executed.

## 12. Pure lifecycle state machine added (not persistence)

`backend/app/services/media_lifecycle.py` implements the allowed status transitions as pure domain logic. It makes only `ready` assets readable; pending, failed, and cleanup-pending assets remain unavailable. A ready asset must first enter `cleanup_pending` before it can become deleted. Deleted is terminal, and repeating the current status is idempotent.

This does not persist state or coordinate Storage/Postgres. A future implementation must enforce transitions atomically (row lock or compare-and-swap), bind idempotency keys to the authenticated owner, verify object existence and metadata before `ready`, and keep cleanup retries safe. The 10 tests in `backend/tests/test_media_lifecycle.py` are authored but have not been executed. No migration, endpoint, worker, or Storage operation was added.

## 13. Immutable replacement planner added (not persistence)

`backend/app/services/media_replacement.py` adds a pure precondition checker for replacement. It requires both old and new records to belong to the verified owner, distinct UUIDs, an old asset in `ready`, and a new asset in `object_uploaded` (meaning the Storage object has already been uploaded and verified). It returns a plan that promotes the new asset to `ready` and moves the old asset to `cleanup_pending`. It does not mutate either input record.

A future implementation MUST perform the active-pointer switch and both status updates in one database transaction (with row locks or optimistic version checks). The new object must be uploaded under a fresh immutable key before that transaction. If upload or verification fails, the old asset remains ready. If the database transaction fails, the old asset remains the active pointer and the new object is an orphan eligible for owner-scoped cleanup. Cleanup must independently verify that no ready row references the old bucket/path before deletion.

Seven tests are authored in `backend/tests/test_media_replacement.py`; they have not been executed. No Storage call, database write, endpoint, migration, or worker was added.

## 14. Owner-scoped cleanup safety gate added (not a worker)

`backend/app/services/media_cleanup.py` adds a pure cleanup planner. It accepts only a server-loaded asset record and the result of a server-side exact-reference check. It requires the authenticated owner to match the row, status to be `cleanup_pending`, a bucket from the private allowlist, and a well-formed object key whose first segment is that owner. It refuses deletion while the exact bucket/object key is still referenced.

The `exact_object_is_referenced` value MUST come from a trusted server-side query over all relevant metadata rows, matching both bucket and exact immutable object key; it must never come from a request parameter or client assertion. The actual worker must re-check references immediately before Storage deletion and use a database lease/lock or equivalent fencing so concurrent replacement cannot race cleanup. After successful Storage deletion, it must persist the `deleted` tombstone idempotently. Storage failure leaves the row `cleanup_pending` for retry.

Seven tests are authored in `backend/tests/test_media_cleanup.py`; they have not been executed. This is not a cleanup worker, Storage delete call, API route, or database transaction.
