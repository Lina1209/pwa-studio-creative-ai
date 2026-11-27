# Character Library importer — browser acceptance plan

Status: test specification only. The importer UI and cloud transfer coordinator are not enabled.

This plan is a release gate for future browser-side local-to-cloud backup. The local passport and IndexedDB image Blobs must remain intact under every failure.

## Test environment

- Use a disposable Supabase-compatible test project or isolated local stack with two test users.
- Never point tests at production Supabase, Storage, or Render.
- Stub network boundaries for deterministic lost-response, offline, delayed-worker, and malformed-response scenarios.
- Use real browser IndexedDB and localStorage in Playwright (or equivalent); do not replace persistence with in-memory mocks.
- Seed each user with a distinct local character UUID and PNG, JPEG, and WebP Blob fixtures.
- Capture SHA-256, byte length, MIME type, decoded width/height, and a byte snapshot before each test.

## Required invariants

1. Canonical local passport and serialized value are unchanged by backup, retry, cancellation, conflict, and rollback.
2. Every source Blob remains readable and matches its original SHA-256 and byte length.
3. A journal entry is committed and read back before the first network request.
4. One local reference maps to at most one cloud asset ID. An idempotency key is never reused for changed bytes, filename, MIME type, or character.
5. `object_uploaded` is intermediate, never a completed backup.
6. A journal item reaches `verified` only after authenticated content read-back and independent browser-side byte/hash/size/MIME/dimension comparison.
7. A guest session never sends cloud passport or image requests.
8. Account switching cannot continue an operation using the previous account's credentials or local namespace.
9. No automatic cleanup request is sent for local source data or cloud assets.

## Scenario matrix

### A. Journal durability

- Create a journal for passports with zero, one, and six references. Assert it is persisted and parsed back before the network spy observes any call.
- Simulate localStorage/IndexedDB quota failure during journal write. Assert zero network calls and no source mutation.
- Corrupt or truncate the journal after a simulated browser restart. Assert safe stop and recovery guidance; do not invent a new idempotency key for an uncertain upload.
- Verify journal version mismatch fails closed without rewriting the source passport.

### B. Passport idempotency

- Create the cloud passport with `source_local_id`; persist the returned cloud ID and read the passport back.
- Drop the create response after server commit. Resume and retry the exact request; assert the same cloud ID is returned.
- Change one metadata field while retaining the same local UUID. Assert conflict and no overwrite.
- Return a passport belonging to another owner. Assert rejection and no image uploads.

### C. Image upload and ambiguous outcomes

- Upload one image through `pending_upload`, `object_uploaded`, then `ready`. Assert only the last state permits content read-back.
- Drop the HTTP response after server reservation. Resume using the same key and exact same Blob; assert one reservation and one asset mapping.
- Drop the response after Storage accepted the object. Assert status reconciliation and no second key.
- Double-tap backup and trigger concurrent resume calls. Assert one operation per local reference and no duplicate cloud mapping.
- Retry the same key with changed bytes, filename, MIME type, or character ID. Assert conflict; never mark verified.
- Return an asset with mismatched owner or character ID. Assert immediate stop and no content read-back.

### D. Independent read-back

- Return exact bytes with matching SHA-256, size, MIME, width, and height. Assert `verified` is persisted and read back.
- Change one byte while preserving declared size. Assert hash mismatch and no verified state.
- Return wrong size, MIME, width, or height independently. Assert each mismatch blocks completion.
- Return HTTP 404/409/502, malformed headers, or truncated content. Assert explicit retryable/terminal classification and unchanged local Blob.
- Return `ready` but make authenticated content read-back fail. Assert the item remains unverified.

### E. Resume, offline, and cancellation

- Interrupt after passport creation, reservation, Storage upload, `ready`, and content download but before journal commit. On restart, resume without creating a second asset.
- Go offline before the first request, between passport creation and image upload, and during read-back. Assert no destructive action and exact-key resume when online.
- Cancel while idle, during upload, and while polling. Assert no new work after cancellation; already-started work is reconciled, never deleted.
- Simulate worker delay and dead-letter status. Assert not backed up; preserve local source for recovery.

### F. Account isolation and guest behavior

- Start as user A, switch to user B while a request is pending, then resolve the old request. Assert the result cannot enter B's journal or UI.
- Attempt to resume A's journal while signed in as B. Assert owner mismatch blocks all network calls.
- Run as guest. Assert local-only messaging and zero cloud API requests.
- Expire auth during polling/read-back. Assert no stale-token retry can mark success.

### G. Completion and rollback

- Complete a character with six references. Assert one cloud passport, six unique mappings, six `ready` states, six byte-for-byte read-backs, and all journal items `verified`.
- Fail the sixth image after five verified images. Assert partial backup, not completion; all six local Blobs remain available.
- Abandon a journal and resume later. Assert safe reuse/revalidation of prior verified items and no source deletion.
- Inspect network traffic. Assert importer issues no Storage DELETE, media DELETE, character DELETE, or local IndexedDB delete.

## Required evidence before enabling the UI

- Automated browser report for every scenario, including browser restart and real IndexedDB persistence.
- Backend tests for owner isolation, idempotent replay, changed-fingerprint conflict, status transitions, and read-back integrity.
- Isolated PostgreSQL/Storage integration results for reservation and verifier behavior.
- Manual review of journal schema, account-switch guards, and cancellation semantics.
- Documentation distinguishes tests actually executed from tests merely specified.

Until all gates pass, keep the cloud backup control disabled and preserve local-only library behavior.
