# Character Library restore checkpoint protocol

Status: design specification only; not implemented or connected to the UI.
Scope: feature branch `feature/character-library-foundation`. No production resources, migrations, Storage objects, or deployments are involved.

## 1. Safety objective

A restore must be resumable after tab closure, browser restart, offline periods, account changes, quota failures, or lost network responses. It must never replace the existing local library until every selected cloud passport and every required reference image has been downloaded and independently verified.

The existing `character-cloud-restore.js` planner is metadata-only and side-effect free. Its current `applyRestorePlan` helper writes metadata through an injected synchronous adapter and deliberately produces empty `referenceImages`; it is not a media restore implementation. Do not treat its passing tests as proof of a complete restore.

## 2. Storage boundaries

The current local data layout is split across two browser stores:
- Owner-specific character metadata: localStorage key `pwa-studio-character-library-v1:<ownerId>`.
- Reference Blobs: IndexedDB database `pwa-studio-character-library-v1`, object store `images`, records keyed by image ID and carrying `ownerId`.

IndexedDB and localStorage do not share a transaction. Therefore a cross-store atomic commit is impossible. The protocol must use staging plus a single atomic metadata activation:
1. Keep the existing metadata array and all referenced image Blobs untouched.
2. Download and verify new Blobs into owner-scoped staging records in the existing images object store (or a dedicated staging store in the same database).
3. Persist a durable restore manifest/checkpoint separately.
4. After all selected cards and all their images are staged and verified, perform one owner-bound `localStorage.setItem` replacing the metadata array with the merged array. This single-key replacement is the activation point.
5. Read back and verify the exact activated metadata.
6. Mark the restore operation committed in its journal.
7. Only later, and only under an explicit retention policy, may staging markers be compacted. Never delete pre-restore records as part of activation.

Staged Blob IDs must be unique, opaque, and collision-checked. They must not reuse an existing local reference ID. Every staging record must include owner ID, operation ID, cloud asset ID, expected digest/size/MIME/dimensions, and staging state. Reads must always enforce owner equality.

## 3. Durable operation record

A restore operation is keyed by a random operation UUID and bound immutably to:
- authenticated owner UUID;
- protocol version;
- creation/update timestamps;
- cloud snapshot identity and first-page snapshot timestamp/token where available;
- original local-library fingerprint and original metadata snapshot reference;
- selected cloud character IDs and stable source-local IDs;
- per-character cloud version and canonical passport digest;
- per-reference cloud asset ID, expected SHA-256, byte size, MIME, width, height, local staged Blob ID, and lifecycle state;
- last fully validated page cursor and page digest;
- operation status and bounded error category.

Suggested operation states:
`planning` → `planned` → `staging` → `ready_to_activate` → `activating` → `committed`.

Terminal or paused outcomes:
- `conflict`: explicit user decision required; no automatic overwrite.
- `paused_retryable`: network, quota, or transient failure; resume from verified checkpoint.
- `aborted`: user cancelled before activation; staged data is retained until safe cleanup.
- `activation_uncertain`: crash or account transition around metadata activation; recovery must inspect the operation marker in the local metadata before deciding whether to resume or roll back.

Never persist bearer tokens, signed URLs, API keys, or other credentials in the journal. Persist only opaque asset IDs and non-secret validation metadata. Obtain fresh authenticated URLs/tokens when resuming.

## 4. Page traversal and cloud snapshot

- Fetch every owner-scoped character page until `next_cursor = null`; enforce existing maximum page, item, and response-size bounds.
- Persist a page checkpoint only after validating the entire page, its cursor, all row identities, versions, and schema.
- Bind each checkpoint to owner, operation ID, snapshot token/timestamp, prior cursor, returned next cursor, and a digest of canonical row identities/version values.
- If the API cannot guarantee a stable snapshot across cursor traversal, detect changes and restart planning rather than combining rows from inconsistent snapshots.
- A failed or malformed page leaves the operation incomplete. Never activate a partial page set.
- Before staging each selected character, re-fetch its canonical passport/version and media manifest. If the version or manifest changed since planning, pause for replanning/conflict review.

## 5. Media staging and independent verification

For each selected cloud reference:
1. Request the asset through the authenticated private-media API; do not use public bucket paths.
2. Enforce maximum response bytes before fully buffering; reject unsupported MIME and malformed dimensions.
3. Stream to a bounded temporary Blob where supported; calculate SHA-256 from the received bytes, not from metadata supplied by the server.
4. Compare actual digest, byte length, MIME, width, and height against the canonical server manifest.
5. Write the Blob to an owner-bound staging record with a fresh local ID; read it back and recompute the same proof.
6. Only after read-back succeeds, mark that reference `verified_staged` in the durable journal.
7. On retry, inspect the existing staging record and its proof. Reuse it only when owner, operation, cloud asset, and all computed bytes/proofs match exactly. Otherwise fail closed and allocate a new staging attempt.

A remote `ready` status alone is not proof of downloaded bytes. A cloud asset ID or client-provided digest is not proof either. No image may enter active `referenceImages` until local Blob read-back verification succeeds.

## 6. Conflict and identity rules

- Local character ID and cloud primary key are separate namespaces and must both be preserved.
- A cloud row may map to a local row only through the explicit persisted `cloudBackup.characterId` binding and stable `source_local_id` contract already enforced by the planner.
- Same passport text is not identity proof.
- Existing local records without a matching cloud binding, mismatched bindings, duplicate mappings, or changed content require explicit conflict resolution. Never silently replace local content.
- Do not infer deletion from absence in a partial page. Bidirectional sync remains disabled until server tombstones and retention semantics are defined.
- The default restore action is additive. It must not delete, rename, or mutate existing local cards or existing image Blobs.

## 7. Atomic activation and crash recovery

The operation must use a unique `restoreOperationId` marker on every newly restored metadata record (inside its cloud-backup metadata) and keep a canonical digest of the complete intended merged array in the operation journal.

Immediately before activation:
- Re-read the owner-specific metadata array.
- Recompute and compare its fingerprint with the original planning snapshot.
- Revalidate owner/session generation.
- Verify every staged Blob again and verify every staged record belongs to this operation and owner.
- Recompute the complete merged array and its digest.
- Confirm the 100-record cap and unique local/cloud/reference identities.

Activation:
- Persist operation status `activating` first.
- Call one synchronous `localStorage.setItem` for the owner key.
- Read back the key and compare the complete canonical digest.
- Mark `committed` only after read-back succeeds.

Recovery after a crash:
- If journal says `activating`, inspect the current owner metadata.
- If every intended record with this `restoreOperationId` is present and the complete merged digest matches, treat activation as committed and finalize the journal.
- If the old snapshot is still present, activation did not occur; keep staged Blobs and allow a safe retry.
- If neither old nor intended digest matches, mark `activation_uncertain` and require manual conflict recovery. Never overwrite the unexpected current library.
- If the account changed, do not perform any write under the newly active account. Resume only after the original owner re-authenticates and the owner-bound adapter is re-created.

## 8. Cleanup and leases

Never run a broad orphan-Blob sweep. A staged Blob not yet referenced by active metadata may belong to another open tab or an in-flight save.

Every staging record must carry an operation ID and explicit lease/ownership state. Cleanup may delete only records whose owner and operation match, whose operation is terminal/expired under a defined lease policy, and which are not referenced by active metadata or another live operation. Recheck those conditions inside the same IndexedDB read-write transaction that deletes the staging record. A stale tab must not be able to delete a newer operation's records.

Aborted operations should first become terminal in the journal; cleanup is a separate retryable task. Partial cleanup must not reactivate deleted metadata or alter the active library.

## 9. Required tests before implementation can be enabled

### Journal and checkpoint
- Schema upgrade preserves all existing journal records.
- Two tabs create/resume the same operation: one lease holder; stale lease cannot advance or clean.
- Owner mismatch, account switch, malformed/tampered cursor, page digest, and operation marker all fail closed.
- Browser restart resumes from the last fully validated page and verified reference.
- Lost response after remote upload/download does not duplicate assets or local references.
- Journal quota/open/write failures preserve source metadata and Blobs.

### Media
- Digest, byte size, MIME, dimensions mismatch each fail independently.
- Truncated stream, oversized body, invalid image decode, and Blob read-back mismatch fail closed.
- Staged Blob is owner-bound and cannot be read/deleted by another owner.
- Existing local Blob bytes remain unchanged throughout all staging and failure cases.

### Activation/recovery
- Crash before staging, mid-download, after Blob write, after journal update, immediately before metadata setItem, immediately after setItem, and before committed journal update.
- Verify old metadata and all old Blobs remain byte-for-byte unchanged before activation.
- Verify activation is idempotently recognized after the post-setItem crash.
- Unexpected concurrent local edit blocks activation and preserves both versions for conflict review.
- localStorage quota/write failure leaves old metadata intact and staged data safely resumable.
- Read-back mismatch enters `activation_uncertain`; never perform blind rollback over a concurrent edit.
- Switch accounts at every async boundary; no write or cleanup crosses owner boundaries.
- 100-record cap, duplicate local/cloud/reference IDs, and 6-reference per-card cap.

### Operational prerequisites
- Exercise workers and media verification only against disposable CI services.
- Prove worker deployment, lease monitoring, retry/dead-letter behavior, and alerts before claiming media processing operational.
- Define tombstones/deletion retention before any bidirectional sync.
- Add user-facing conflict review, progress, pause/resume, cancel, and recovery UX before product activation.

## 10. Explicit non-goals

This specification does not authorize:
- connecting restore to `app.js` or adding a visible restore button;
- changing the current metadata-only backup action;
- creating or changing production Supabase objects, Storage objects, or worker services;
- enabling a cloud image provider or paid generation service;
- deploying, merging, or changing `main`.

Decision: implement and test the durable journal/coordinator in isolated modules first. Keep cloud restore/import disabled until every required test and operational prerequisite above passes.


## 10. Isolated checkpoint journal implementation (feature branch)

Status: the persistence primitive is implemented in `character-restore-journal.js`; it is not wired to the restore planner, media downloader, local Blob store, activation, or UI.

- Uses a dedicated IndexedDB database `pwa-studio-character-restore-journal-v1`, separate from the existing backup journal database. No migration of either existing database is required.
- Stores owner-bound operation records with immutable operation/owner identity, protocol version, local base fingerprint, snapshot identity, bounded selected character IDs, page checkpoint, bounded per-reference verification descriptors, revision, and lifecycle state.
- Revalidates persisted records on every read/list and before every mutation. Unknown states, malformed UUIDs, invalid digests, unsupported MIME types, oversized references, duplicate assets, invalid timestamps, and owner/key mismatches fail closed.
- Uses atomic IndexedDB read-write transactions for lease acquisition and checkpoint compare-and-swap. Lease epochs increase monotonically; an expired lease can be replaced, but the previous token/epoch cannot advance or release the operation afterward.
- Checkpoint updates require the current unexpired lease, exact expected revision, and an allowed state transition. The journal stores only opaque identifiers and validation metadata; it has no API/network code and accepts no bearer token or signed URL fields.
- Owner-indexed pagination is bounded to 1–100 rows and cursors are owner-bound. The journal does not perform image downloads, Blob writes, cleanup, or localStorage activation.
- Browser tests cover create/read persistence, owner isolation, duplicate/competing lease claims, revision CAS, illegal transitions, lease expiry/takeover and stale-holder fencing, release, reference proof validation, bounded pagination, cursor owner fencing, and tampered-record rejection.

Validation: GitHub Actions run `46104006239` on commit `f7cfa3b` completed successfully; backend unit tests, disposable PostgreSQL integration, and real-browser IndexedDB/frontend checks all passed.

Remaining limitations are intentional: no real process-kill recovery test, browser offline resume, actual quota exhaustion, multi-tab UI integration, cloud snapshot traversal, media staging/read-back, restore coordinator, activation recovery, or UI wiring. A journal checkpoint is not proof that an image has been downloaded or that a restore is complete. Keep restore/import disabled until the coordinator and all activation safeguards in this document are implemented and tested.
