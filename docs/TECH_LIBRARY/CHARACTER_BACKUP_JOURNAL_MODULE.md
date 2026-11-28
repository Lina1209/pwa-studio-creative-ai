# Character backup journal module

Status: isolated browser persistence primitive in the feature branch. Its real-browser acceptance suite has passed on the latest reviewed source; it is still not loaded by the application and does not enable cloud import.

## File and loading boundary

- Implementation: `character-backup-journal.js`.
- Exposes frozen `globalThis.PWACharacterBackupJournal` when loaded as a classic script.
- The module is intentionally not referenced by `index.html` or `app.js`.
- It makes no fetch/XHR calls, does not read Supabase credentials, and has no Storage access.
- It never reads, writes, or deletes the canonical character localStorage record or source image IndexedDB store.
- Its only persistence target is a separate IndexedDB database named `pwa-studio-character-backup-journal-v1`, object store `journals`.

## API

- `create({ ownerId, localCharacterId, passportFingerprint, references })`: creates one journal, rejects duplicate keys, persists it, reads it back, and compares the read-back record.
- `get(ownerId, localCharacterId)`: retrieves one owner-scoped journal.
- `listPage(ownerId, { limit, cursor })`: returns bounded owner-index pages (1–100 records) with an owner-bound cursor.
- `list(ownerId)`: compatibility helper for the first page only; it fails rather than silently truncating when additional pages exist.
- `setCloudCharacter(ownerId, localCharacterId, cloudCharacterId)`: stores a single immutable cloud character mapping.
- `transition({ ownerId, localCharacterId, localReferenceId, state, cloudAssetId?, errorCategory? })`: applies only the declared state transitions; cloud asset mapping is immutable; `verified` requires a cloud asset ID.
- `completionStatus(record)`: reports complete only when a cloud character mapping exists and every reference is verified with a cloud asset mapping and verification timestamp.

Reference descriptors must contain:
- `localReferenceId`
- `sha256` (64 lowercase/uppercase hexadecimal characters)
- `sizeBytes` (1–8 MiB)
- `mimeType` (PNG, JPEG, or WebP)
- `fileName` (maximum 120 characters)
- `idempotencyKey` (persisted before any future network operation)

Owner and character IDs must be UUIDs; guest scope is intentionally unsupported. At most six references are accepted. Journal keys are owner + local character UUID. A cloud ID cannot silently be replaced. A reference idempotency key and source fingerprint are immutable after journal creation.

## State safety

The state machine is restrictive: only `object_uploaded` may transition to `verified`; a reserved or merely pending upload cannot be marked verified. Verified, conflict, and terminal_error are terminal. Conflicts cannot be silently retried. A verified transition requires a persisted cloud asset ID. The journal does not itself prove that remote content is valid: a future coordinator must independently perform authenticated status polling, download/read-back, and byte/hash/size/MIME/dimension comparisons before requesting the verified transition.

## Verification still required

The isolated persistence primitive has a real-browser acceptance suite. The following additional cases remain required before wiring it into the UI:
- IndexedDB durability after reload and browser restart;
- owner separation and account switching;
- duplicate creation within one tab and racing creation from two independent browser tabs; aborted IndexedDB write rollback with no partial journal record;
- simulated `QuotaExceededError` during IndexedDB open (not physical storage exhaustion), source Blob preservation, and transaction abort;
- invalid/forbidden state transitions and immutable mappings;
- lost network response and offline recovery in the future coordinator;
- proof that source localStorage and image Blob records remain byte-for-byte unchanged.

Do not enable an importer, add network orchestration, or remove local source data until the browser acceptance plan passes. No production database or Storage operations are part of this module.

## Automated browser acceptance suite

- Browser page: `tests/browser/character-backup-journal.html`.
- Runner: `tests/browser/run_character_backup_journal.py`.
- CI job: `character-backup-journal-browser-tests` in `.github/workflows/feature-branch-tests.yml`.
- The runner serves the repository over loopback HTTP and launches a fresh Chromium context. IndexedDB data is isolated to that temporary browser context.
- Current cases: create/read-back while asserting an existing local image Blob remains byte-for-byte unchanged, duplicate creation rejection, concurrent duplicate creation in one tab and across two independent tabs (exactly one winner), owner-scoped get/list including identical local character IDs under two different owners, immutable cloud character mapping, malformed passport fingerprint rejection, rejection of skipped upload states and premature verified transitions, valid lifecycle through verified, completion criteria, terminal verified state, aborted-transaction rollback, simulated IndexedDB quota/open failure with source Blob preservation, and a late IndexedDB success callback after a blocked upgrade (the late connection must be closed). The runner also reopens the same persistent Chromium profile and verifies journal recovery after browser restart.

The suite simulates an IndexedDB `QuotaExceededError` at database-open time and verifies that the source Blob and journal remain unchanged. This is not a physical browser storage-exhaustion test. The suite does not yet simulate process termination mid-transaction, real quota exhaustion, account-switch UI behavior, or network recovery. Those remain required before importer integration.


## 2026-11-28 review notes

- Latest reviewed feature-branch source: `character-backup-journal.js` SHA `ac3538befb0cbecc834de925a6a0b8ba936173cc`; repository SHA `26c2fad0b89e7b7d1c32d0a868fca954c328853f`.
- CI run `46099783129` completed successfully: backend unit tests, PostgreSQL media-cleanup integration, and real-browser character backup journal tests all passed. Run `46099779456` also completed with all three jobs successful.
- The journal remains an isolated browser module, not loaded by the product UI. CI proves the tested browser persistence behaviors only; it does not prove a complete cloud backup/import workflow.
- The journal now uses IndexedDB schema v2, an owner index, bounded `listPage()` cursor traversal, and deep persisted-record validation. The v1-to-v2 migration preserves legacy records; its browser regression uses a dedicated legacy owner to avoid cross-test contamination.
- `assertRecord` validation is a local integrity check, not a trusted server boundary; a future cloud coordinator must independently validate all journal fields before sending any request.
- Real storage exhaustion, forced browser-process termination mid-transaction, account-switch UI integration, and network/offline resume are not covered yet. Keep the source passport and image Blobs untouched; do not enable import until those cases and server read-back verification are covered.
- No production database, Storage, or deployment operation was performed.


- CI runs `46103404601` and `46103408877` both passed all three jobs on commit `cea8f2d`: backend unit tests, disposable PostgreSQL integration, and real-browser IndexedDB journal/frontend checks. The browser job passed the v1-to-v2 migration, preservation of existing records, and owner-index query checks. The PostgreSQL job completed adversarial reference-write race and 50-event/five-worker cleanup stress checks.
- Current journal source SHA at this checkpoint: `817e64c7e86cce200393bee0d56e5f4d52398e44`. The module remains isolated and is not connected to app UI, cloud upload, or restore.
- Remaining pre-integration gaps include forced process termination mid-transaction, real storage exhaustion, account-switch UI integration, offline/network resume, and a durable coordinator spanning cloud assets and local metadata. No restore/import activation is approved by these tests.
