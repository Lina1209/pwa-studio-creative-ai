# Character Cloud Sync Protocol — Design Gate

Status: feature-branch implementation in progress. Changes are confined to `feature/character-library-foundation`; no production migration or deployment has occurred.

## Current implementation boundary

The authenticated character API in `backend/app/character_api.py` now exposes owner-scoped keyset pagination, signed owner-bound cursors, and version-checked PATCH operations. Migrations `0023` and `0024` add optimistic concurrency and the pagination index. Disposable PostgreSQL CI and backend tests cover stale writes, ownership, pagination, and concurrent compare-and-swap behavior.

The Character Library UI now has an explicit metadata-only cloud backup action for signed-in users. It traverses every API page, maps local IDs to cloud IDs via `source_local_id`, creates missing passports idempotently, updates existing passports only with their current version, and stops on conflicts. Operations are fenced to the originating account. Local records and IndexedDB image Blobs are never modified by this action.

The browser backup journal now upgrades to IndexedDB schema v2, adds an owner index, and exposes bounded `listPage(ownerId, {limit, cursor})` traversal (1–100 rows) with owner-bound cursors. The compatibility `list()` helper returns only its first bounded page. Journal records are validated deeply before reads and state mutations; malformed owner mappings, fingerprints, timestamps, reference metadata, cloud IDs, and verification proofs fail closed. Browser tests cover multi-page completeness, owner isolation, cursor tampering, and corrupted persisted records.

A separate `character-cloud-restore.js` module now implements a side-effect-free restore planner. It fetches and validates every API page, fences account changes, rejects duplicate cloud/local identity mappings, proposes new local records using the stable local ID, preserves the cloud ID/version mapping, and reports local-vs-cloud conflicts instead of overwriting. It deliberately does not write localStorage, IndexedDB, or download media. Reference-image descriptors are retained as a manifest while `referenceImages` stays empty so the restored card does not point to missing local Blobs.

This is not yet an enabled restore or media backup. The restore planner is not connected to the UI or commit layer; resumable page checkpoints, deletion/tombstone semantics, conflict resolution UX, and end-to-end browser account-switch tests remain outstanding. Keep restore/import disabled until those paths are implemented and tested.

## 1. Optimistic concurrency for edits

### Proposed data contract

- Add a non-null integer `version` to each cloud character, initialized to 1.
- Every successful metadata mutation increments `version` exactly once in the same database transaction as the field update.
- The client must send `expected_version` with every PATCH.
- The server validates it as a positive integer (reject booleans, floats, strings, zero, and negatives).
- A single service-role-only SECURITY DEFINER RPC performs the owner-scoped compare-and-swap:
  1. Lock the target row.
  2. Confirm both `id` and authenticated server-derived `owner_id`.
  3. Compare current version with `expected_version`.
  4. If different, make no change and return a conflict outcome.
  5. Validate and apply only the allowed mutable fields.
  6. Increment version and return the canonical row.
- Map stale-version outcomes to HTTP 409 with a stable machine-readable error code such as `character_version_conflict`. Do not reveal whether another user's character exists.
- Remove the direct PostgREST PATCH path after the RPC is ready. Browser roles must have no direct write grant that bypasses version checks.
- Keep service credentials server-side. The RPC must have a fixed safe `search_path`, explicit grants, and owner identity supplied only from the verified server principal.

### Retry and conflict behavior

- A retry carrying an old expected version must not silently overwrite newer data.
- On 409, the client fetches the current passport and presents a deliberate merge/reload decision; it must not automatically replay the old patch against the new version.
- A lost response after a successful write is handled by fetching current state. Do not treat a stale retry as a successful idempotent write.
- If request-level idempotency is later required, design it separately with a durable request key bound to owner, character, expected version, and canonical payload digest.

## 2. Bounded, stable pagination

### Proposed list contract

- Replace the hard-coded 100-row list with cursor pagination. Suggested response: `items`, `next_cursor`, and `snapshot_created_at`.
- Sort by immutable `created_at DESC, id DESC`; the unique ID is the tie-breaker.
- Use keyset pagination, not offset pagination. The next page predicate must be lexicographically older than the last returned `(created_at, id)` pair.
- The first page establishes an upper-bound snapshot timestamp. Subsequent pages carry that bound and exclude rows created after it, preventing newly-created records from shifting the traversal.
- Validate and sign/encode cursor data server-side (or use an opaque authenticated token); never accept arbitrary PostgREST filters from the browser.
- Enforce a small fixed page-size ceiling (recommended maximum 100) and reject malformed, oversized, or tampered cursors.
- Keep ordering fields immutable. If future product requirements sort by mutable `updated_at`, this cursor design must be revisited because edits can move rows between pages.
- Return only public passport fields; never expose owner IDs, storage bucket/path, internal moderation or cleanup state.

### Restore semantics

- A restore operation must traverse every page until `next_cursor = null`; one page is never evidence that the full library was retrieved.
- Deduplicate locally by cloud character ID and stable `source_local_id`, while rejecting conflicting mappings rather than overwriting either identity.
- Keep local IDs and cloud primary keys distinct.
- Treat a failed page as an incomplete restore. Preserve already-downloaded local data and resume from a validated cursor; never mark restore complete on partial results.
- Define deletion/tombstone semantics before supporting bidirectional sync. Pagination alone does not convey deleted records.

## 3. Required acceptance tests before enabling restore

### Versioning
1. Two clients read version 1; first update succeeds and returns version 2.
2. Second update with expected version 1 returns 409 and changes no fields.
3. Wrong owner receives indistinguishable 404; no cross-owner disclosure.
4. Concurrent compare-and-swap attempts result in exactly one successful update.
5. Every successful update increments exactly once; validation/RPC/audit failures roll back without increment.
6. Browser/anon/authenticated roles cannot call the RPC or directly mutate character rows.
7. A response-loss retry with the old version cannot overwrite the committed update.

### Pagination
1. More than 100 rows are returned across bounded pages with no duplicates or omissions.
2. Equal `created_at` timestamps are ordered deterministically by ID.
3. New records inserted after page one do not appear inside the established snapshot.
4. Tampered, malformed, expired (if expiry is adopted), and oversized cursors are rejected.
5. Every page is owner-scoped and foreign rows fail closed.
6. A failed middle page leaves restore marked incomplete and safely resumable.
7. Query plans use an appropriate composite index and remain bounded under a large owner's library.

### Integration and operations
- Test migrations and RPC races only in disposable CI PostgreSQL, never production as part of this design task.
- Test the actual API response contract and browser account-switch behavior.
- Keep cloud restore/import disabled until pagination, versioning, deletion semantics, worker deployment/monitoring, and end-to-end restore tests are all accepted.
- Do not add a worker service, apply migrations, alter live Supabase, or deploy without separate explicit approval.

## Implementation status — feature branch only

Implementation has now been added for the API foundations and the local journal safety layer:

- Migration `0023_character_versioned_updates.sql` adds a positive monotonic `version` and a service-role-only compare-and-swap RPC. It also updates the idempotent create RPC response to expose the initial version.
- The character PATCH API requires `expected_version`; stale writes return HTTP 409 with `character_version_conflict`.
- Migration `0024_character_cursor_pagination_index.sql` adds the composite owner/created_at/ID index.
- The list API now returns `items`, `next_cursor`, and `snapshot_created_at`, with a maximum page size of 100. Cursors are owner-bound, HMAC-signed, expire after 15 minutes, and use descending keyset pagination on immutable `created_at, id`.
- Backend unit/API tests and disposable PostgreSQL assertions cover version conflicts, owner isolation, cursor tampering, page bounds, and the pagination index.
- `character-backup-journal.js` uses IndexedDB schema v2 with an owner index and bounded local cursor pagination. Browser tests cover two-row pages across seven records, owner-bound/tampered cursors, page-size limits, and fail-closed validation of modified stored records.
- The journal remains a persistence primitive only: no network calls and no media upload.
- `character-cloud-restore.js` is a separate, side-effect-free planner; it does not write to localStorage/IndexedDB or connect to the UI.
- Node tests cover full multi-page traversal, local/cloud ID preservation, missing-media manifest handling, unchanged records, conflict reporting, duplicate mappings, malformed API rows, and account-switch aborts.

Validation checkpoint: CI run `46100463960` passed all three jobs (backend unit tests, disposable PostgreSQL integration, and real-browser IndexedDB journal tests) for the versioned-update and cursor-pagination implementation. The additional concurrent compare-and-swap harness also passed in CI run `46100552578`: two independent PostgreSQL clients used the same expected version, exactly one update succeeded, one returned a stale-version conflict, and the stored version incremented only once. The browser restore workflow still does not consume every API page, and the local journal has not been connected to this API. Do not enable restore/import based on these API foundations alone.

## Decision

Keep cloud restore/import disabled until the latest CI run passes, browser account-switch and resumable multi-page restore integration is implemented, deletion/tombstone semantics are defined, and worker deployment/monitoring is approved. No production migration or deployment is part of this work.
