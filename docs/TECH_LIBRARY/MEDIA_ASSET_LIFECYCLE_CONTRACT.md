# PWA Studio — private media asset lifecycle contract

**Status:** private media read/sign API routes and server-side read services exist on the feature branch; upload, delete, cleanup, and frontend integration remain inactive.
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

At this revision, authenticated private-image content proxy and short-lived signed-URL routes exist on the feature branch. There is still no upload, replace, delete, or cleanup API/worker, and no frontend media-library/character-card integration. No route has been deployed or verified against live Supabase Storage. `image_reference_validation.py` now performs full bounded Pillow decoding, but does not normalize images, strip EXIF, or isolate decoding in a separate OS-limited worker. Migration 0017 is a draft schema hardening change, not a deployed policy. This contract must not be interpreted as an implemented upload or cloud-backup feature.

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

At the time this repository primitive was introduced, no FastAPI route or Storage operation existed. The later authenticated read/sign routes are documented in sections 21–22. The returned metadata includes `storage_path` for trusted internal follow-up only; routes must not serialize it to the browser. The new mocked unit tests are in `backend/tests/test_media_repository.py`; they have not been executed.

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

## 15. Concurrent mutation guard added (not database concurrency control)

`backend/app/services/media_concurrency.py` adds a pure optimistic-concurrency check. A mutation is accepted only when the caller's expected row version equals the current database version and its fencing token equals the current lease fencing token. It returns the next version and rejects stale workers, stale edits, malformed operation IDs, invalid counters, and signed-bigint version exhaustion.

This helper does NOT issue leases, increment counters, lock rows, persist idempotency keys, or prevent races by itself. Production persistence MUST:
1. acquire/renew a lease and increment a monotonically increasing fencing token atomically in Postgres;
2. read the row under `SELECT ... FOR UPDATE` (or use a conditional UPDATE that checks owner, status, version, and fence);
3. apply the mutation only if the expected version and current fence still match;
4. increment the row version in the same transaction;
5. make every worker write include the fence so an expired worker cannot commit after a newer worker;
6. re-check exact object references and acquire the cleanup lease in the same serialization boundary immediately before deleting from Storage, then finalize the tombstone idempotently.

A lease timeout alone is not proof that an old worker stopped. Fencing is mandatory: every stale worker must be unable to commit even if it wakes after lease expiry. Storage deletion is an external side effect and cannot be rolled back with Postgres; use a durable cleanup job/outbox and idempotent retries, with the object already made unavailable before deletion.

Seven tests are authored in `backend/tests/test_media_concurrency.py`; they have not been executed. No lease table, migration, RPC, transaction, endpoint, worker, or Storage call was added.

## 16. Durable media outbox lifecycle model added (not persistence)

`backend/app/services/media_outbox.py` defines the pure event lifecycle for future background work: `pending` → `claimed` → `delivered`, with retry back to `pending` or terminal `dead_letter`. Claims require a UUID token and bounded lease; acknowledgement/retry require the matching unexpired token. Expired claims can be recovered, and attempt limits prevent infinite retry loops. Event types are a closed allowlist (`media_cleanup_requested`, `media_upload_verify_requested`); payload design intentionally carries opaque IDs, not bytes, credentials, signed URLs, or client paths.

Ten tests are authored in `backend/tests/test_media_outbox.py`; they have not been executed. No outbox table, database RPC, scheduler, broker, worker, or Storage operation was added.

### Required durable implementation before activation

- Insert the media metadata row and its outbox event in the SAME Postgres transaction. Never commit a pending upload/cleanup request without its corresponding durable event.
- Claim batches with `FOR UPDATE SKIP LOCKED`, set a fresh random claim token and expiry, and increment attempts atomically.
- Acknowledge, retry, and finalize only with a conditional update matching event ID, current claim token, and unexpired lease. A stale worker must not acknowledge a newer claim.
- Workers must be idempotent because delivery is at-least-once, not exactly-once. Use operation IDs and immutable object keys; verify current metadata state before every side effect.
- On worker crash, recover expired claims. After max attempts, move to dead-letter and alert; never silently discard.
- Keep events private to service role. Do not expose raw Storage paths or event payloads to browser clients.
- For cleanup, re-check exact references under the database serialization boundary immediately before Storage deletion; finalize the tombstone only after Storage confirms success. If Storage outcome is ambiguous, reconcile object existence before retrying.
- For upload verification, only transition to `ready` after the object is verified and the owner-bound metadata transaction succeeds.

The model is intentionally not a queue implementation. The actual transactional outbox requires a reviewed schema/RPC and disposable-database concurrency tests before any migration can be considered for deployment.

## 17. PostgreSQL transactional outbox design (not an active migration)

The detailed design is in `docs/TECH_LIBRARY/MEDIA_OUTBOX_POSTGRES_DESIGN.md`. It defines atomic metadata+event transactions, owner-scoped idempotency, `FOR UPDATE SKIP LOCKED` claims, fenced acknowledgements, crash recovery, and safe ordering for upload verification and cleanup.

No SQL migration or RPC was added because the current `media_assets` draft schema does not yet contain the final status/version/operation columns and has not been reconciled against a disposable database. The design is intentionally non-executable. Do not apply it to production or treat it as a live queue.

## 18. Character-reference upload composition boundary

Added `backend/app/services/media_workflow.py` as a pure composition layer. It checks the authenticated owner against the server-loaded character row, fully validates image bytes and declared MIME, restricts the bucket, builds the immutable object key from server-side UUIDs, and creates the matching upload-verification outbox event model. It returns a server-internal plan with the initial `pending_upload` state.

The helper does not write the asset row, insert the outbox event, upload bytes, or return a URL. The future API must persist asset metadata and event in one transaction, perform the Storage upload using the internal plan, and never serialize `storage_path`, bucket, owner metadata, or raw internal metadata to the browser. A public response must use the explicit `media_asset_public_view()` allowlist from `media_access.py`.

Also tightened cleanup path validation: a deletable object key must have exactly four segments, an allowlisted resource kind and extension, and canonical UUID resource/object segments. Tests were added for malformed keys and for the public metadata projection.

Seven composition tests are authored in `backend/tests/test_media_workflow.py`; tests have not been executed. This is still a planning boundary, not an active upload route or Storage integration.

## 19. Character-reference replacement composition boundary

Added `backend/app/services/media_replacement_workflow.py`. It composes the immutable replacement planner with the character ownership check, current-reference precondition, private-bucket allowlist, and strict validation that both old and new server-stored object keys belong to the same owner and character. It creates a cleanup outbox event bound only to the superseded asset.

The result is a plan, not a mutation. The future persistence adapter must, in ONE Postgres transaction and under a row lock or equivalent compare-and-swap:
1. verify the character still points to the expected old asset;
2. promote the verified new asset to `ready`;
3. move the old asset to `cleanup_pending`;
4. switch the character's active reference pointer;
5. insert the unique cleanup outbox event.

If any step fails, all database changes must roll back and the old ready reference remains active. Storage deletion happens later in a worker, after it rechecks exact bucket + object-path references. The cleanup event is not permission to delete immediately. The schema currently has no explicit canonical avatar/reference pointer column, so that column and its ownership FK must be designed before wiring this plan to a route. The seven replacement-workflow tests are authored but have not been executed.

### Replacement-boundary hardening follow-up

The replacement composition guard now canonicalizes the authenticated owner, character ID, and current-reference asset ID before comparison. Both old and new media rows must explicitly reference the same character; an absent `character_id` is no longer treated as acceptable for a character-reference replacement. This prevents a generic unattached media row from being promoted through the character replacement path. Three additional unit tests cover absent associations, canonical UUID spellings, and malformed current pointers. These tests are authored only and have not been executed.

## 19. Private read authorization planner added (not a read endpoint)

`backend/app/services/media_read.py` adds a pure eligibility gate for future private-media reads. It requires the verified owner to match the stored asset owner, the asset status to be exactly `ready`, an allowlisted private bucket, and a server-stored immutable object key whose owner/resource/object UUIDs and extension satisfy the key contract. It rejects pending, uploaded-but-not-ready, failed, cleanup-pending, and deleted assets.

The owner-filtered repository now selects the stored `bucket` and `status` fields needed by this gate. The path and bucket remain server-internal and must never be serialized to the browser. This planner itself does not issue a signed URL or download bytes. The authenticated read/sign routes added later call `get_owned_media_asset` using the verified JWT subject, apply this gate, and only then perform the private Storage operation. Signed URLs must not be logged or persisted.

Six unit tests are authored in `backend/tests/test_media_read.py`; they have not been executed. No Storage request, route, migration, or production change was made.

## 20. Short-lived signed URL service added

`backend/app/services/media_signed_url.py` adds a server-only function that requests a Supabase Storage signed URL with a fixed 60-second expiry. It accepts only a `MediaReadPlan` produced after the owner-filtered metadata lookup and read-eligibility gate; it does not accept bucket, object path, or expiry from browser input. The Supabase service-role credential remains in the server request. The returned URL is accepted only as a relative Storage signing path and is pinned to the configured Supabase project host. Storage errors are converted to generic responses without relaying provider details.

At the time this service was added, no FastAPI route invoked it. The authenticated `/access` route described in section 21 now performs that sequence. Never persist, cache, log, or publish the signed URL. Treat it as a bearer capability until expiry.

Four mocked unit tests are authored in `backend/tests/test_media_signed_url.py`; they have not been executed. No live Storage request was made, no endpoint was added, and no production setting or database was changed.

## 21. Authenticated private media access route added

`GET /api/media/{asset_id}/access` is now wired in `backend/app/main.py` behind `get_current_user`. It derives the owner only from the verified Supabase JWT subject, loads the asset through `get_owned_media_asset` (including same-owner project/character checks), applies the `ready`/private-bucket/immutable-path gate, and only then asks Supabase Storage for a 60-second signed URL.

The response contains the short-lived `signed_url`, `expires_in`, and the explicit `media_asset_public_view` allowlist. It does not return owner ID, bucket, object path, or private metadata. The route sets `Cache-Control: private, no-store, max-age=0` and `Pragma: no-cache`. Missing/foreign and non-ready assets do not reach the signer. The URL itself remains a bearer capability and must not be persisted or logged by clients.

Mocked route tests are authored in `backend/tests/test_private_media_route.py` for success, safe projection, no-store headers, absent/foreign access, non-ready rejection, and missing authentication. They have not been executed. The route is committed to the feature branch but has not been deployed or verified against a live Supabase project. Do not enable production use until tests and the two-account Storage integration matrix pass.

## 22. Authenticated image proxy added for revocable access checks

`GET /api/media/{asset_id}/content` is a private image proxy for media-library and character-card previews. It re-authenticates each request, reloads the media row through the owner-filtered repository, verifies linked-resource ownership, requires `ready`, and validates the private bucket and immutable object key before downloading bytes from Storage.

The proxy is deliberately image-only (PNG/JPEG/WebP) and enforces the same 8 MiB maximum as reference images. It streams the Storage response in bounded chunks, rejects an oversized declared or observed body, then fully decodes and verifies the image with the existing Pillow validation. It returns the image bytes directly with `Cache-Control: private, no-store`, `nosniff`, same-origin resource policy, and a restrictive content security policy. It does not expose a Storage URL or internal object path.

Because the database authorization/status check runs on every proxy request, a later request is denied after the asset is tombstoned/deleted or no longer ready. An already in-flight response cannot be recalled, and bytes already delivered to a client cannot be made to disappear. The separate `/access` signed-URL endpoint remains a bearer-capability path: a previously issued signed URL may remain usable until its 60-second expiry or Storage-side object removal. Sensitive previews should prefer the authenticated proxy.

Tests are authored in `backend/tests/test_private_media_route.py` and `backend/tests/test_media_content.py` for no-store headers, deleted-asset denial, size limits, MIME restrictions, and image validation. They have not been executed. The frontend has not yet been changed to fetch this endpoint with its Supabase access token and render a temporary in-memory object URL; no production or live Storage request has been made.
