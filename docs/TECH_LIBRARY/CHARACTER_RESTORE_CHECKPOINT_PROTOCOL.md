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


## 11. Verified media staging coordinator (feature branch; activation remains separate)

Status: `character-restore-coordinator.js` now implements an injected-adapter staging coordinator. It is not connected to the application UI or production APIs.

- Requires an existing owner-bound restore operation at the expected revision and an eligible `planned`, `staging`, or `paused_retryable` state.
- Acquires the journal's fenced lease, then re-reads the operation and verifies that lease acquisition changed the revision exactly as expected before any media work.
- Validates the bounded manifest (up to 600 references), unique cloud asset IDs, SHA-256, byte size (1–8 MiB), supported image MIME, and expected dimensions.
- Downloads through an injected adapter only; computes SHA-256 from the received Blob bytes and independently checks size, MIME, and image dimensions.
- Stages each Blob through an injected owner/operation-scoped adapter, reads it back, and repeats digest/size/MIME/dimension verification before marking that reference `verified_staged` in the durable journal.
- On retry, already verified staged Blobs are read back and reverified instead of blindly trusted. An interrupted write before checkpoint can safely retry the same deterministic staged Blob identity.
- Account-current checks fence work before/after awaits. Errors leave the operation retryable when the same account and lease remain valid; stale/expired leases cannot checkpoint. The coordinator releases its lease best-effort.
- Returns only a staging result with `activationRequired: true`. It does not write localStorage metadata, publish restored cards, delete data, or activate a restore.

Validation: CI run `46104623804` on commit `32f9a8e` passed all three jobs (backend unit tests, disposable PostgreSQL integration, and browser/IndexedDB plus frontend checks). The Node coordinator harness covers successful byte-proof/read-back staging, tampered staged Blob rejection, and account-switch fencing. Earlier coordinator test failures were traced to a test runtime Web Crypto global assignment and a mismatch between manifest and computed-proof field names; both were corrected before this successful run.

Remaining limitations: the coordinator uses injected adapters and has no production media API or IndexedDB Blob adapter yet; no real cloud transfer, browser offline/network resume, forced process-kill recovery, actual quota exhaustion, lease heartbeat for long-running transfers, multi-tab UI, full 600-image stress test, metadata activation/recovery, tombstones, or restore UX. A successful staging result is not a completed restore. Keep restore/import disabled until the activation coordinator, recovery protocol, adapters, and full interruption/race tests are implemented.


### Real-browser coordinator integration validation

A Playwright/Chromium integration page now runs the coordinator against the actual IndexedDB restore journal and real browser Blob/Web Crypto APIs (with deterministic injected media adapters). It verifies:
- successful staging reaches `ready_to_activate` only after Blob read-back proof is persisted;
- tampered read-back bytes are rejected and the operation becomes `paused_retryable`;
- account switching during download prevents later staging/checkpoint writes and releases the lease.

CI run `46104818818` on commit `6dcbe09` passed all three jobs, including this real-browser coordinator integration test, the existing restore/backup journal browser suites, backend unit tests, and disposable PostgreSQL integration. This validates the injected-adapter boundary and journal integration; it does not validate a real cloud media endpoint or production Blob adapter.

## Lease renewal hardening (2026-11-28)

The restore journal now exposes an atomic `renewLease(ownerId, operationId, lease, {ttlMs})` operation. Renewal:
- requires the current owner, token, and monotonic lease epoch;
- refuses an expired, stale, or replaced lease;
- extends expiry without changing the checkpoint revision, so it cannot invalidate an in-flight revision-CAS checkpoint;
- remains bounded to 1–120 seconds.

The media staging coordinator renews its 60-second lease every 20 seconds while staging. A renewal failure permanently fences that coordinator attempt: it stops before the next media/checkpoint boundary, does not attempt an unsafe stale-owner rollback, and leaves the operation available for a later lease holder to inspect and resume. The heartbeat is stopped and any in-flight renewal settled before lease release.

Real-browser tests now cover successful renewal, stale-token rejection, renewal after lease takeover, and monotonic epoch fencing. The coordinator's existing browser and unit tests continue to exercise staging, tampered read-back, and account-switch fencing.

This improves long-transfer resilience but does not make browser timers reliable during device sleep or browser suspension. If a tab is suspended beyond the lease expiry, the attempt must fail closed and resume under a newly acquired lease. No production UI, cloud media endpoint, metadata activation, or deployment is enabled by this change.


## 12. Isolated IndexedDB Blob staging adapter (feature branch)

Status: `character-restore-blob-store.js` now provides an injected, owner- and operation-scoped adapter over the existing `pwa-studio-character-library-v1/images` object store. It is not wired into the application runtime; a real-browser integration test now injects it into the staging coordinator.

- Reuses the existing database and object-store schema; no version bump or migration is required.
- Writes staged records with the existing `id`, `ownerId`, `blob`, and `createdAt` fields plus a `restoreStage` descriptor containing operation ID, cloud asset ID, and the expected byte/dimension proof.
- Rejects invalid UUID identities, unsupported or malformed proof metadata, and collisions with records owned by another account or operation.
- Allows an idempotent retry only when owner, operation, cloud asset, and proof metadata match. The coordinator must still read the Blob back and recompute its proof; matching metadata alone is not trusted.
- Reads return a Blob only when owner, operation, asset, and staged ID all match. Other-owner or other-operation lookups return null.
- The adapter intentionally has no delete/cleanup API. Safe cleanup requires a separate lease- and active-reference-checked protocol and must not be inferred from an unreferenced Blob.

The real-browser Playwright test uses actual IndexedDB and Web Crypto to check write/read, idempotent retry, owner and operation isolation, collision rejection, and malformed proof rejection. CI wiring runs this browser test and checks the adapter's JavaScript syntax.

This adapter is an isolated persistence primitive, not evidence of a complete restore. It does not download media, inspect image dimensions, activate metadata, clean up staged records, or connect to the UI. Keep restore/import disabled.


### Additional browser regression coverage

The real-browser coordinator suite now also checks recovery from a retryable interruption: a failed verification is resumed with the same durable operation, and the staged media is verified before the operation returns to `ready_to_activate`. Separate negative cases verify that MIME, byte length, SHA-256, and image dimensions mismatches stop before the Blob staging adapter is called. These are deterministic browser tests against the real IndexedDB journal; they do not exercise a real cloud endpoint or production account.


## 13. Mandatory explicit reference-to-asset binding gate

The activation design depends on an exact join between each passport reference and its private media asset. The current API does not establish that join: passport descriptors contain a local `id`, while the upload endpoint derives an independent cloud asset UUID from an idempotency key and does not persist the local reference ID. The listing endpoint returns cloud asset IDs and integrity metadata but no local reference ID. The content proxy verifies bytes but cannot establish semantic association to a passport slot.

Consequently, the current `referenceManifest[].id` is **not** a `cloudAssetId`. Do not infer equivalence or match by filename, order, MIME, dimensions, or image similarity. The activation coordinator must reject manifests unless every descriptor has a server-confirmed, owner- and character-bound mapping to exactly one ready asset.

Required future API fields are `local_reference_id`, `asset_id`, `character_id`, `status`, `file_name`, `file_type`, `size_bytes`, `content_sha256`, `width`, and `height`. The local reference ID must be accepted only as a validated UUID or exact stable composite key and persisted atomically with the media reservation. The list endpoint must return the explicit mapping without exposing owner IDs, bucket names, Storage paths, internal metadata, or signed URLs. Uniqueness and ownership must be enforced in a reviewed migration and disposable PostgreSQL tests.

Until this API contract and its cross-owner/idempotency tests exist, no metadata activation implementation may consume the current media manifest. Keep restore disabled; the existing staging-only coordinator remains isolated and must not be connected to the UI.


## 14. Explicit cloud media catalog and planner join

The authenticated bulk catalog endpoint is `GET /api/media/character-references?character_ids=<comma-separated UUIDs>`, bounded to 1–100 requested cloud characters and at most 600 media rows. Its response exposes only the safe mapping and integrity tuple; owner ID, bucket, Storage path, signed URLs, and internal metadata are never returned.

The planner's `fetchReferences(characterIds)` adapter is called in batches of no more than 100 characters. It must return the endpoint's catalog rows. The planner joins descriptors only by exact `character_id + local_reference_id`, requires one-to-one mapping, `status=ready`, matching MIME, SHA-256, byte size, and dimensions, and writes the validated cloud asset ID plus expected integrity proof into the restore checkpoint manifest. Legacy assets with null local-reference IDs are ignored as unmapped. No filename/order/image-similarity heuristics are allowed.

This enables the staging coordinator to download the exact asset IDs and verify the received bytes against the recorded proof. It does not activate local metadata or create local reference Blobs by itself. UI activation remains disabled pending the separate atomic-activation and crash-recovery implementation.


Each staged reference checkpoint also preserves `characterId` (cloud character UUID), `sourceLocalId` (local card UUID), `localReferenceId` (the original stable local reference key), display name, and MIME. The staging coordinator carries these fields unchanged from the planner into the durable journal. This prevents the activation phase from having to reconstruct or guess which staged Blob belongs to which restored card/reference slot.


## 15. Durable activation-intent checkpoint (isolated journal foundation)

The restore journal now has an optional validated `activation` record containing:
- `baseDigest`: SHA-256 of the exact owner-local metadata snapshot used for activation;
- `mergedDigest`: SHA-256 of the complete canonical intended merged metadata array;
- `intendedCount`: expected total metadata record count (1–100);
- `operationMarker`: must equal the journal's immutable restore operation UUID;
- `preparedAt`: timestamp for the activation intent.

A transition into `activating` is rejected unless this complete intent is persisted in the same journal checkpoint. The journal permits an interrupted `activating` operation to become `paused_retryable` while retaining its intent, and permits an `activation_uncertain` operation to be explicitly returned to retryable review. These transitions do not themselves perform recovery or authorize a metadata write.

The browser journal suite now verifies that an activation transition without intent is rejected, a valid intent survives a checkpoint/read-back, malformed digests are rejected, and an interrupted activation can be paused without losing the intent.

This is only the durable intent primitive. There is still no activation coordinator, canonical merged-array builder, staged-Blob revalidation at activation time, localStorage commit, read-back recovery, or crash-boundary integration test. Do not enable restore/import or connect this journal field to the application UI.


## 16. Guarded metadata activation coordinator (not UI-connected)

A separate `character-restore-activation.js` coordinator now implements the guarded activation boundary using injected owner-scoped adapters:

1. Requires the journal operation to be `ready_to_activate`, obtains a fenced lease, and checks the post-lease revision.
2. Requires a fresh complete, conflict-free planner result whose selected cloud identities match the durable operation (including explicitly unchanged cards).
3. Hashes the planner's canonical local snapshot and compares it with the durable base digest; it also re-reads the owner-local metadata and requires an exact canonical match.
4. Requires every staged reference to be `verified_staged`, checks the exact character/local-reference/asset mapping against the fresh manifest, re-reads each staged Blob by owner + operation + asset + staged ID, and recomputes SHA-256, byte size, MIME, and dimensions.
5. Builds additive card metadata only. Existing local cards remain in place. New `referenceImages` entries use the staged Blob's actual local IndexedDB key as `id`, preserve the original cloud local-reference key as `sourceReferenceId`, and carry the existing display name/MIME fields. Each new card receives a `restoreOperationId` marker.
6. Computes the complete canonical merged-library digest, persists the activation intent in the journal, then performs one synchronous owner-scoped localStorage key replacement and verifies the read-back digest and operation markers before checkpointing `committed`.

No compensating deletion or blind rollback is attempted after the metadata commit point. If a write/read-back boundary is interrupted, the durable intent is retained. `recoverActivation` compares the current local metadata against the intended merged digest and base digest: a complete intended result can be marked committed, the untouched base can be marked retryable, and any third state is classified as a conflict. Recovery never overwrites the current library.

Real-browser integration tests cover successful activation with preserved existing data, image bytes and dimensions being checked before activation, refusal on dimension mismatch without metadata mutation, and recognition of a completed metadata write after a simulated crash.

This is still an isolated foundation. No application UI or automatic cloud restore flow calls this coordinator. No cleanup/deletion of staged Blobs, tombstones, deployment, or production migration is included. The next validation step is the new GitHub Actions browser job; activation remains disabled until it passes and further crash/account-switch boundary tests are completed.


### Validation result

The activation coordinator and journal changes passed GitHub Actions run `46108551390` on feature-branch commit `e1c4d4a`: backend unit tests, disposable PostgreSQL integration, all existing IndexedDB/browser suites, activation browser integration (4 scenarios), and frontend syntax/account-switch checks. The activation browser scenarios cover successful staged-media verification and additive activation, tampered dimensions rejected before metadata mutation, storage quota failure preserving the original library with a retryable checkpoint, and recovery after a simulated crash between metadata write and journal commit. This validation is feature-branch CI only; it does not authorize UI wiring or production deployment.


### Additional account-switch validation

A fifth activation browser scenario now switches the active-account fence immediately after the staged Blob is read. The coordinator refuses to continue, leaves local metadata byte-for-byte unchanged, and does not advance the operation beyond `ready_to_activate`. GitHub Actions run `46108643132` on commit `693e65a` passed all three jobs: backend unit tests, disposable PostgreSQL integration, and the full browser/IndexedDB suite including all five activation scenarios.


### Real localStorage integration

The activation browser suite now uses the browser's actual `window.localStorage` implementation rather than an in-memory Map shim. The quota-failure adapter wraps the real read path and injects a failing write, confirming that the exact base library remains intact and the durable operation is retryable. GitHub Actions run `46108806956` on `df458f6` passed all three jobs, including the five activation scenarios and frontend checks.


### Full document-reload recovery proof

The simulated crash-recovery browser scenario now navigates to a separate recovery document after persisting the activation intent and writing the merged metadata, but before marking the operation committed. The new document reopens the IndexedDB journal, reconstructs the owner-scoped localStorage adapter, and invokes recovery using only the durable operation ID and revision. It proves that the merged digest and restore-operation marker survive a full page reload before committing the journal. GitHub Actions run `46108898647` on `0fcfd1f` passed backend unit tests, disposable PostgreSQL integration, all IndexedDB/browser tests, and frontend checks.


### Recovery account-switch fence

Recovery now rechecks the active-account fence after loading the durable journal, after acquiring the lease, after reading local metadata, and immediately before changing the journal state. A browser test flips the account fence after the metadata read: recovery refuses to checkpoint, leaves the operation in `activating`, and succeeds only after the correct account context is restored. GitHub Actions run `46108991587` on `db04ed6` passed backend unit tests, disposable PostgreSQL integration, and the complete browser/IndexedDB suite.


### Recovery boundary matrix

Recovery browser coverage now exercises all three outcomes: (1) the exact merged digest plus expected operation markers becomes `committed`; (2) the untouched base digest becomes `paused_retryable`; (3) any third metadata state becomes `conflict` without rollback or overwrite. The journal transition table explicitly allows `activating → conflict` for the third case. GitHub Actions run `46109097295` on `960f620` passed backend unit tests, disposable PostgreSQL integration, and the complete browser/IndexedDB suite.


## 17. Staged Blob cleanup protocol (design gate; no deletion implementation)

Status: protocol design only. The Blob adapter intentionally remains write/read-only. No cleanup method, cleanup worker, UI action, or deletion has been added.

### Why operation leases alone are insufficient

The current journal lease is scoped to one restore operation. Two different operations for the same owner can therefore hold separate leases concurrently. That does not serialize cleanup against activation: a cleanup pass could inspect one operation while another operation is about to activate a staged Blob. A check followed by an IndexedDB delete is also unsafe if another tab can publish a reference between those steps.

Consequently, cleanup MUST NOT be implemented using only per-operation leases or a scan for unreferenced image rows.

### Shared owner-level critical-section lock

Before any cleanup implementation, introduce one owner-scoped coordination lock shared by activation and cleanup:

- Store lock records in a dedicated coordination IndexedDB database, separate from the image Blob database and restore journal. This avoids changing either existing database schema.
- Lock identity is the validated owner UUID; record includes opaque token, monotonically increasing fencing epoch, expiry timestamp, and bounded protocol version. Never store credentials.
- Acquisition, renewal, takeover, and release use atomic IndexedDB read-write transactions. A live lock cannot be stolen; expired lock takeover increments the epoch. Every mutation verifies owner, token, epoch, and unexpired lease.
- Activation must acquire this same owner lock before its final local metadata snapshot / staged-Blob verification / activation-intent and metadata commit critical section. It must recheck the account fence and lock immediately before the synchronous metadata write. Cleanup must hold the same lock from its complete reference inventory through the final delete transaction.
- Both paths retain their per-operation journal leases as well. The owner lock serializes cross-operation critical sections; the operation lease fences the specific journal record.
- Heartbeat/renewal is mandatory for long work. A failed renewal permanently fences that attempt. Browser suspension beyond expiry means stop; a later holder must re-read all state from scratch.
- No path may wait indefinitely while holding the lock. Bound lock duration, candidate count, and work per pass. Release is best effort; expiry is the recovery mechanism.

The lock is a cooperative protocol: every code path that can activate or delete restore-staged Blobs must use it. Until activation is updated to participate, cleanup remains prohibited.

### Candidate eligibility: deliberately narrow

A candidate must satisfy ALL conditions:

1. It is an image row with a valid `restoreStage` descriptor. Ordinary legacy/user image rows without that descriptor are never candidates.
2. The exact tuple `ownerId + operationId + cloudAssetId + localStagedBlobId` matches a validated reference in the corresponding durable restore journal record.
3. The operation is explicitly `aborted`, or is otherwise eligible only after a separately specified retention policy has marked it terminal. `committed`, `conflict`, `activation_uncertain`, and every nonterminal/paused state are retained by default. A conflict is not proof that its staged data is disposable.
4. The operation has no live operation lease, and no newer owner/operation epoch or cleanup claim supersedes the candidate.
5. The exact staged Blob ID is not referenced by any active local card metadata, including cards not created by this restore.
6. No nonterminal, retryable, uncertain, or otherwise retained restore operation references the same staged Blob ID or asset mapping.
7. The active owner/account fence still matches. Any malformed journal, unreadable metadata, incomplete journal inventory, pagination error, quota error, or ambiguous identity blocks the entire candidate batch.

No filename, age-only, missing-journal, or unreferenced-row heuristic is sufficient. Unknown rows are retained, not deleted.

### Two-phase mark, recheck, delete

Cleanup is a resumable, idempotent operation with its own UUID and durable audit state. It does not mutate active character metadata.

Phase A — mark:
- Acquire the owner lock and validate its current fencing epoch.
- Read the complete owner-local metadata array and compute a canonical digest.
- Read every owner journal page to exhaustion using bounded pagination; validate every row and cursor. Do not infer completeness from a partial page.
- Identify a bounded candidate set from explicit `restoreStage` descriptors and matching journal references.
- Persist a cleanup manifest containing only owner/operation/asset/staged IDs, candidate proof digest, observed journal revision/state, observed metadata digest, owner-lock epoch, and timestamp. No Blob bytes or secrets.
- Mark candidates `cleanup_pending` in the cleanup manifest only; do not alter restore operation state or delete anything.
- Release the lock. A delay/retention interval separates marking from deletion so an interrupted or newly referenced item can be detected.

Phase B — delete:
- Reacquire the same owner lock with a new valid fencing token/epoch and recheck the active account.
- Re-read and hash current local metadata; re-read every journal page; verify candidate operation/revision/state, absence of live leases, absence of any active reference, and absence of any retained operation reference.
- If any observed digest, revision, identity, or eligibility condition changed, cancel that candidate as retained/conflict; do not delete it.
- For each candidate, open a read-write transaction on the existing image database, fetch the exact staged row, and revalidate owner + restoreStage operation + asset + staged ID + proof identity before deleting that exact key. A missing row is an idempotent already-deleted result only if the durable cleanup manifest proves that exact candidate; otherwise it is an identity conflict.
- Record `deleted` only after the IndexedDB delete transaction completes. If the browser crashes between deletion and audit update, a retry sees the exact row missing and can reconcile the already-deleted result using the durable manifest.
- Never issue a range delete, clear the object store, or delete by owner prefix.

The localStorage and IndexedDB stores still cannot share a transaction. The shared owner lock closes the activation-vs-cleanup race only for cooperating code paths. If the lock is lost, cleanup stops before its next delete; it must not attempt a stale release or continue using a stale inventory.

### Cleanup manifest states

Suggested per-candidate states: `marked` → `deleted`; alternate outcomes `retained`, `cancelled_changed`, `identity_conflict`, `blocked_incomplete_inventory`. The cleanup operation itself is resumable and owner-bound. It has a monotonic revision and fenced lease, and stores bounded error categories rather than raw server messages.

No automatic cleanup of committed restore staging is allowed in this phase. A future retention policy may consider committed staging only after proving that the active metadata references a different verified local Blob ID and no restore/recovery path needs the staged source. That policy requires a separate review and tests; it is not implied by this protocol.

### Mandatory race and failure tests before any delete API

Use real browser IndexedDB, real localStorage, multiple pages/tabs, and disposable databases:

- preserve every ordinary image row, including legacy rows with no `restoreStage`;
- preserve a staged row referenced by active metadata, even if its operation is aborted;
- preserve a staged row referenced by any other live, paused, retryable, conflict, or uncertain operation;
- reject malformed or duplicate owner/operation/asset/staged-ID mappings and incomplete journal pagination;
- two operations for one owner cannot hold the owner lock simultaneously;
- stale owner-lock token/epoch cannot renew, release, mark, or delete after takeover;
- activation and cleanup contend for the same owner lock: whichever acquires first completes its bounded critical section; the other re-reads all state and cannot use stale inventory;
- a new activation cannot publish a Blob while cleanup holds the owner lock;
- account switch before marking, between phases, during a batch, and immediately before delete blocks further mutation;
- crash after mark, after delay, after final recheck, after IndexedDB delete but before audit checkpoint, and during partial batch is safely resumable;
- repeated cleanup is idempotent and never deletes a different row after key reuse/collision;
- quota, blocked database, malformed journal, localStorage read failure, lock renewal failure, and browser suspension all fail closed;
- a 100-card / 600-reference owner inventory remains bounded and pagination is exhausted before deletion begins.

### Explicit implementation gate

Do not add a delete method to `character-restore-blob-store.js` until:
1. the owner coordination lock is implemented and tested in real-browser multi-tab scenarios;
2. activation acquires and renews that same lock around its final verification and metadata commit boundary;
3. cleanup manifest persistence, two-phase recheck, and crash reconciliation are implemented;
4. every mandatory race test above passes in feature-branch CI.

No production database, Storage object, migration, account, or deployment is involved. UI remains disconnected and cleanup remains disabled.


## 18. Owner coordination lock foundation (implemented; not yet used by activation)

The isolated module `character-owner-coordination-lock.js` now implements the shared owner-level lock foundation described above:

- Dedicated IndexedDB database `pwa-studio-character-owner-coordination-v1`, store `locks`, keyed by validated owner UUID. It does not change the existing image database or restore journal schema.
- Atomic read-write transactions implement acquisition, renewal, takeover, and release.
- Each lease carries an opaque token, monotonically increasing owner epoch, bounded expiry, and protocol version. Active locks cannot be acquired twice; expired locks can be taken over only with a higher epoch.
- Renewal, release, and `isCurrent` are fenced by owner + token + epoch; expired or stale holders cannot renew or release a replacement lease.
- The module has no network, UI, Blob deletion, journal mutation, or application wiring.

Real-browser tests cover simultaneous acquisition, independent owner locks, renewal, expiry takeover, and stale-holder fencing. A separate Playwright runner opens two actual browser pages on the same origin and verifies that exactly one can acquire the same owner's lock.

CI run `46109529483` on feature branch commit `989be93` passed all three jobs, including the initial lock browser suite and all existing backend/PostgreSQL/browser checks. The test was subsequently strengthened to use two actual pages; its final CI result is pending at the time of this note.

Important remaining gate: `character-restore-activation.js` does NOT yet acquire this owner-level lock. The lock is currently an isolated primitive, not an enforced cross-operation barrier. Therefore no cleanup/delete API may be added or invoked. Next, integrate the shared lock into activation and crash recovery, test activation-vs-activation and activation-vs-lock contention across tabs, and only then implement the two-phase cleanup manifest. Cleanup remains design-only and disabled.


## 19. Owner lock integrated into activation and recovery (feature branch)

The guarded activation and crash-recovery entry points now require the shared owner coordination lock. Both acquire locks in one deterministic order: owner-wide critical-section lock first, then the operation-specific restore-journal lease. This prevents two restore operations for the same owner from entering the metadata activation/recovery critical section concurrently.

Activation holds the owner lock while it:
- obtains and revalidates the operation checkpoint;
- re-reads and hashes the local metadata and all staged Blobs;
- persists activation intent;
- performs the single synchronous local metadata replacement and read-back digest check;
- checkpoints the committed state.

Both operation and owner leases are renewed by the activation heartbeat. A failed renewal, expired lease, stale fencing epoch, or account switch stops further mutation. Release is best effort; expiry and fencing remain the recovery mechanism.

Crash recovery follows the same lock order and holds the owner lock while it reads local metadata, compares the durable base/merged digest boundary, and checkpoints `committed`, `paused_retryable`, or `conflict`. It never rolls back an ambiguous third metadata state.

The real-browser activation and reload-recovery pages load the actual owner lock module, so existing activation tests now exercise the shared critical-section lock rather than a mock. The owner lock remains cooperative: any future activation/deletion path must use it. No cleanup/delete method exists yet. The expanded cross-tab activation-versus-cleanup race matrix remains a prerequisite before cleanup implementation.


## 20. Owner-lock contention verification

The real-browser activation suite now explicitly holds the owner critical-section lock from a competing operation and verifies:

- activation fails closed before acquiring its operation lease;
- local metadata remains byte-for-byte/canonically unchanged;
- the restore operation remains `ready_to_activate` with no lease mutation;
- crash recovery likewise cannot inspect-and-checkpoint while another tab holds the owner lock;
- the recovery operation remains `activating` and its journal lease remains unclaimed.

CI run `46109968273` on commit `f636626` passed all three jobs. The browser job passed the full restore activation/reload-recovery suite, owner-lock multi-tab suite, and frontend syntax/account-switch checks; backend unit tests and disposable PostgreSQL integration also passed.

### Cleanup implementation remains intentionally blocked

The owner lock is now enforced by both restore activation and recovery, and contention is covered. However, the existing application UI's general local-library write paths have not yet been audited or brought under this owner lock. A cleanup worker must not delete staged rows until every path capable of creating or changing a reference to a staged Blob is proven to participate in the same owner critical section. Therefore the Blob store still has no delete API; no cleanup job, automatic sweep, or user-facing cleanup control is enabled.


## 21. Local Character Library UI mutation audit and lock coverage

The frontend mutation-path audit identified two direct UI mutation handlers in `app.js`:

1. Character/scene save and edit: writes reference Blobs to the existing `images` store, then replaces the owner metadata key in localStorage.
2. Character/scene deletion: removes the card metadata, then attempts to remove its reference Blobs.

Both handlers now acquire the shared owner coordination lock before the final metadata snapshot and hold it across Blob writes/deletes and the localStorage commit. The save handler re-reads the complete owner metadata after lock acquisition and refuses to overwrite a snapshot changed by another tab. The lock renews while asynchronous image work is in progress; stale/expired lock or account-switch checks fail closed. Guests remain local-only and cannot enter authenticated cloud restore.

Image-write collision behavior was tightened: a new reference uses IndexedDB `add`, never `put`; any pre-existing row at that key is preserved and the save aborts. This prevents an accidental ID collision from overwriting a staged restore Blob or another existing image.

Image deletion now parses the complete owner metadata key and refuses to delete a Blob if any card still references its ID. Missing legacy `referenceImages` arrays are treated as empty, while malformed metadata/shape, unreadable localStorage, or an incomplete (>100) library blocks deletion. Shared references are retained and surfaced as partial cleanup rather than reported as deleted. On account switch or lost owner lock, failed-save cleanup leaves temporary images in place rather than mutating storage under a stale context.

The owner coordination lock script is loaded before `app.js` and added to the versioned service-worker shell cache for offline startup. A static contract test checks load order, offline precache, both lock acquisitions, fresh metadata re-read, collision-safe image writes, and cross-card reference protection.

Scope note: this audit covers every direct Character Library metadata key and image-store mutation found in the current frontend source. Cloud backup reads local metadata and writes only authenticated cloud passport metadata; it does not upload or delete local image Blobs. Movie-project, profile-avatar, and unrelated localStorage writes are separate stores and are not part of this Character Library lock.

The first CI run exposed three outdated source-contract assertions and then one remaining assertion about partial cleanup. Those tests were updated to reflect the stronger owner-lock and shared-reference behavior. The next CI run is the acceptance gate for these frontend changes. No cleanup sweeper or staged-Blob delete API has been added.


## 22. Mark-only cleanup journal and candidate planner (implemented; deletion disabled)

Two new isolated modules now implement the first durable cleanup phase:

- `character-restore-cleanup-journal.js` stores append-only owner-bound cleanup manifests in its own IndexedDB database `pwa-studio-character-restore-cleanup-journal-v1`. It validates owner/cleanup UUID identity, revision, owner-lock epoch, metadata digest, candidate identity, SHA-256, byte size, MIME, dimensions, timestamps, and duplicate staged IDs. It provides create/read/bounded owner pagination only. There is no manifest mutation or Blob deletion method.
- `character-restore-cleanup.js` exports `PWACharacterRestoreCleanup.markAbortedRestoreBlobs`. It acquires the shared owner lock, snapshots and hashes complete local metadata, reads the full restore-journal inventory (deliberately limited to one complete page of at most 100 operations), and considers only references in explicitly `aborted` operations with `verified_staged` proof and no live operation lease.

The planner builds owner-wide maps before candidate selection. It retains a Blob if its staged ID appears in any active card, if the cloud asset mapping appears in another restore operation, or if the staged ID is shared by another operation. It reads the exact owner/operation/asset/staged-ID tuple through the existing Blob adapter and recomputes SHA-256, byte size, MIME, and dimensions from the stored Blob. Missing, malformed, mismatched, incomplete, or over-limit inventory fails closed.

A successful mark writes a deterministic cleanup manifest with a minimum 24-hour retention deadline. Repeating the same mark against the same metadata and candidate proof returns the existing manifest instead of duplicating it. The operation lock is renewed during asynchronous reads and checked before the durable manifest write. Account switches or lock loss stop the pass.

Real-browser tests use actual IndexedDB, localStorage, Blob bytes, WebCrypto, and the shared owner lock. They cover successful marking without deleting bytes, deterministic idempotency, active-card retention, nonterminal/cross-operation asset retention, owner-lock contention, and account-switch fencing. CI run `46110872865` on feature branch commit `bd558f4` passed all three jobs, including the new mark-only cleanup browser suite.

### Explicit remaining safety gate

This phase only records delayed candidates. It does not implement the retention-expiry recheck, candidate cancellation/reconciliation, cleanup-manifest state transitions, or any Blob delete operation. A later phase must re-read the complete metadata and journal inventory under the owner lock after the retention deadline, verify the original operation revision and proof again, reconcile interrupted batches, and only then consider a separately reviewed exact-key IndexedDB delete transaction. No cleanup UI, background worker, automatic sweep, or production data operation exists.


## 23. Retention-gated cleanup recheck (read-only; no delete)

The cleanup planner now also exposes `PWACharacterRestoreCleanup.inspectMarkedManifest`. This is a second, read-only phase:

- Acquires the same owner-wide lock and renews it while reading.
- Refuses to proceed until every candidate's 24-hour retention deadline has passed.
- Re-reads and hashes the complete local metadata; any metadata digest change blocks the entire manifest.
- Re-reads the complete bounded restore journal (up to 100 operations) and checks the source operation is still the exact recorded revision, remains terminal `aborted`, and has no live lease.
- Rebuilds owner-wide staged-Blob and cloud-asset maps; any active metadata reference, cross-operation staged ID, reused cloud-asset mapping, changed checkpoint proof, missing Blob, or failed byte/dimension verification blocks the candidate batch.
- Returns only a read-only `eligible_for_delete_review` result when all checks still match. This result is advisory and is not a delete authorization token; a future delete implementation must repeat the full checks while holding the owner lock immediately before its exact-key transaction.

Browser tests verify retention cannot be bypassed, an expired candidate passes the read-only proof recheck, the staged Blob remains present afterward, and any changed local metadata blocks the manifest. CI run `46111142768` on commit `a082776` passed all three jobs, including the new cleanup retention/recheck browser cases.

No deletion method, cleanup manifest mutation, automatic worker, or UI control has been added. The next gate is durable candidate cancellation/reconciliation and crash-safe per-candidate deletion design, followed by additional multi-tab race tests. Until those are complete, staged Blobs are never removed by this cleanup subsystem.


## 24. Durable cleanup reconciliation and monotonic lock epochs

The cleanup journal now supports one atomic compare-and-swap reconciliation from `marked` to `reconciled`. Each candidate receives exactly one durable outcome:

- `eligible_for_delete_review` with a recheck timestamp, or
- `retained` with a bounded reason code such as `metadata_changed`, `source_changed`, `reference_changed`, `proof_changed`, or `blob_missing`.

The reconciliation transaction preserves every candidate identity/proof field, checks the expected manifest revision, and requires a strictly newer owner-lock epoch. Repeated inspection of a reconciled manifest is read-only and idempotent. A retained candidate cannot be promoted by a second inspection; a new fresh mark would be required after a new snapshot.

A fencing issue found during this work was corrected: successful owner-lock release now leaves a tombstone containing the last epoch rather than deleting the lock row. The next acquisition therefore advances the epoch after both release and expiry/takeover. Real-browser tests verify release → reacquire increments the epoch and that stale holders remain fenced. Cleanup recheck tests verify the manifest stores the newer epoch, persists eligible/retained outcomes, and leaves Blob bytes untouched.

CI run `46111523702` on commit `5e92777` passed all three jobs, including the complete browser cleanup-mark/recheck suite, owner-lock tests, backend unit tests, and disposable PostgreSQL integration tests.

This is still not deletion authorization. `eligible_for_delete_review` is only a durable advisory state. Any future delete transaction must acquire a fresh owner lock and repeat all metadata, journal, source revision, reference-map, Blob identity, and byte-proof checks immediately before deleting the exact staged Blob key. No Blob deletion API exists.


## 25. Per-candidate deletion intent primitives (not wired to an executor)

The next implementation slice adds two narrowly scoped primitives, but deliberately does not expose a cleanup runner or UI:

1. `PWACharacterRestoreCleanupJournal.beginCandidateDelete` performs an IndexedDB compare-and-swap from `eligible_for_delete_review` to `delete_intent`. It requires the expected manifest revision, candidate's exact staged Blob ID, a unique delete-attempt UUID, and a strictly newer owner-lock epoch. The intent (including timestamp and epoch) is durable before any Blob deletion is attempted.
2. `PWACharacterRestoreBlobStore.deleteStagedBlob` deletes only the exact IndexedDB key when owner ID, restore operation ID, cloud asset ID, and the complete persisted SHA/size/MIME/dimensions proof all match in the same read-write transaction. Identity/proof mismatch aborts without deleting. A missing row returns `missing`, allowing a future executor to recover a crash after the delete transaction but before journal completion.
3. `PWACharacterRestoreCleanupJournal.finalizeCandidateDeleted` records completion only for the matching durable delete attempt, expected revision, `deleting` manifest, and a newer owner-lock epoch. A manifest becomes `completed` only when every candidate is either `deleted` or `retained`.

The real-browser test now exercises the sequence: advisory eligibility → durable delete intent → exact-key deletion → release/reacquire owner lock → durable completion. This models a crash boundary between the Blob transaction and journal completion; the next holder can finish the same attempt without guessing another key. Additional Blob tests prove cross-owner, cross-operation, and proof-mismatch requests are rejected and that exact deletion retry is idempotent.

The adapter primitive is not a complete deletion workflow. There is still no production caller, automatic worker, or UI. Before any executor can be enabled it must repeat the complete metadata and restore-journal inventory checks under the owner lock immediately before writing intent, verify the candidate is still eligible and its 24-hour retention elapsed, then delete and finalize one candidate at a time. It must also recover existing `delete_intent` records by exact identity, and fail closed on incomplete inventories, account switches, lock loss, stale revisions, and ambiguous storage errors. Existing ordinary character images are never eligible for this API because they lack the exact `restoreStage` tuple and proof.


## 26. Current application writer-path audit and primitive verification

A fresh inspection of the current `app.js` character-library section confirms the authenticated owner-scoped write paths use the shared owner coordination lock:

- New reference Blob writes occur in the save flow while the owner lock is held; metadata activation is fenced by a fresh library snapshot and the same lock.
- Card deletion first commits the owner-scoped metadata update while holding the lock, then attempts per-reference deletion through `deleteCharacterImage`.
- Reference removal during card edit is committed under the same lock, then its old image cleanup runs before releasing the lock.
- `deleteCharacterImage` re-reads the owner metadata and refuses deletion when any card still references the image; it also requires the exact row owner in IndexedDB.
- Restore staging and activation use the same owner lock. The guest library path is not eligible for restore cleanup because restore journal operations require a UUID owner.

The current audit is scoped to the character-library metadata and image store paths above; it is not a claim that unrelated application localStorage keys participate in this lock.

CI run `46111985459` on commit `f6f2c7d` passed all three jobs. The real-browser suite verified the exact-key deletion adapter and the durable intent → Blob delete → lock reacquire → journal completion sequence. This is test-harness coverage only; no cleanup executor is wired into `app.js`, no worker is scheduled, and no existing user image is swept.


### Additional byte-integrity hardening

The exact Blob delete adapter now requires an injected image inspector and performs a preflight read of the actual staged Blob. Before opening the read-write delete transaction it recomputes SHA-256 from the received bytes, checks byte size and MIME, and rechecks image dimensions against the durable proof. The caller is required to hold the owner-wide lock for the entire preflight/delete sequence; the transaction then rechecks the exact owner/operation/asset/proof tuple before deleting the key. Browser tests deliberately replace stored bytes while leaving the proof metadata unchanged and verify that deletion is rejected and the Blob remains present.


The final exact-byte deletion adapter test run is CI `46112211648` on commit `3add0af`: all three jobs succeeded (backend unit tests, disposable PostgreSQL integration, and the full browser/IndexedDB suite). The browser suite includes a same-size Blob byte-tampering attempt, and verifies checksum mismatch prevents deletion. Cross-owner and cross-operation delete attempts fail closed as `missing` without touching the real owner's staged Blob.


## 27. Isolated exact-key cleanup executor (feature branch)

Status: an injected executor primitive now exists in `character-restore-cleanup-executor.js`. It is not connected to the app, UI, a worker, a scheduler, or any production resource. No cleanup has been run against user data.

Before each candidate, the executor:
- requires a reconciled manifest and an elapsed 24-hour retention timestamp;
- acquires the owner-wide lock, checks the current account context, and renews the lock on a heartbeat throughout the preflight/deletion window;
- reads the complete owner restore-journal inventory with bounded pagination (maximum 100 pages / 10,000 rows), rejecting malformed, foreign, or incomplete records;
- recomputes the owner metadata digest and proves the exact staged reference is absent;
- confirms the source operation is still aborted, its revision is unchanged, its lease is expired, and no other restore operation references the same staged Blob or cloud asset;
- compares the source checkpoint's complete image proof to the manifest;
- writes a durable per-candidate delete intent before calling the exact-key Blob deletion adapter;
- releases and reacquires the owner lock before journal finalization, requiring a newer fencing epoch and the same delete-attempt identity.

The executor defaults to one candidate per invocation (hard maximum ten). It never scans or deletes ordinary image rows. A missing Blob during a normal delete attempt is treated as an uncertain/manual-recovery condition, not success. A pre-existing delete intent is recoverable from the durable `deleting` manifest state only when the exact Blob lookup reports missing after a fresh complete inventory and the intent identity still matches; the journal is then finalized under a newer owner-lock epoch. If the Blob still exists after an uncertain prior intent, execution stops for manual recovery.

Safety gate: a dedicated disposable-IndexedDB Playwright suite now exercises the injected executor against real browser storage. The initial executor suite passed CI run `46113264575` (all three jobs succeeded), covering exact staged-Blob deletion while preserving an unrelated staged Blob, account-switch fencing, metadata drift, and incomplete restore-journal pagination. The executor now renews the owner lock on a heartbeat and rechecks the fencing token immediately before deletion. The expanded six-case executor browser suite passed CI run `46113466882` on commit `b248088`: exact staged-Blob deletion with unrelated-Blob preservation; account-switch fencing; metadata drift rejection; recovery after a crash between exact Blob deletion and journal finalization; lock-loss rejection after durable intent; and incomplete pagination rejection. The same run passed the safe site-cache browser tests, all other Character Library browser/IndexedDB suites, backend unit tests, and disposable PostgreSQL integration/race/stress tests. The matching PR validation run `46113469970` also succeeded. This is not full approval: active/paused/uncertain operation races, lease expiry, crash windows at every boundary, multi-tab contention, and legacy-image preservation still require expanded tests and review. Keep cleanup execution disabled and unwired until those gates pass and the caller is separately reviewed.


## 28. User-facing PWA cache maintenance

The Settings page now exposes **Очистить кеш сайта** for every visitor/account, not only administrators. It deletes only Cache Storage entries whose names begin with `pwa-studio-shell-`, then refreshes the page. The shell cache version was advanced so clients can receive the updated app shell.

This is a per-browser/per-device action. It does not clear localStorage, IndexedDB, character images, drafts, cloud projects, authentication, preferences, or server-side/CDN caches. It cannot repair a server outage or remove data stored on another device. The user receives a confirmation explaining the preserved data and a status message.

Global cache purges, server/CDN cache invalidation, and administrator maintenance controls are separate operational features and are not implemented by this button. No admin-only access is required for a user clearing their own browser cache.
