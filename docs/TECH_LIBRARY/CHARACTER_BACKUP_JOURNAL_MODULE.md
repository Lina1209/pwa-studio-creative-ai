# Character backup journal module

Status: isolated browser persistence primitive in the feature branch. It is not loaded by the application and does not enable cloud import.

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
- `list(ownerId)`: returns only journals for the requested authenticated UUID.
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

This commit adds the isolated persistence primitive only. It does not claim browser acceptance tests passed. Before wiring it into the UI, add automated real-browser tests using disposable browser storage for:
- IndexedDB durability after reload and browser restart;
- owner separation and account switching;
- duplicate creation within one tab and racing creation from two independent browser tabs;
- quota failure and transaction abort;
- invalid/forbidden state transitions and immutable mappings;
- lost network response and offline recovery in the future coordinator;
- proof that source localStorage and image Blob records remain byte-for-byte unchanged.

Do not enable an importer, add network orchestration, or remove local source data until the browser acceptance plan passes. No production database or Storage operations are part of this module.

## Automated browser acceptance suite

- Browser page: `tests/browser/character-backup-journal.html`.
- Runner: `tests/browser/run_character_backup_journal.py`.
- CI job: `character-backup-journal-browser-tests` in `.github/workflows/feature-branch-tests.yml`.
- The runner serves the repository over loopback HTTP and launches a fresh Chromium context. IndexedDB data is isolated to that temporary browser context.
- Current cases: create/read-back while asserting an existing local image Blob remains byte-for-byte unchanged, duplicate creation rejection, concurrent duplicate creation in one tab and across two independent tabs (exactly one winner), owner-scoped get/list, immutable cloud character mapping, malformed passport fingerprint rejection, rejection of skipped upload states and premature verified transitions, valid lifecycle through verified, completion criteria, and terminal verified state. The runner also reopens the same persistent Chromium profile and verifies journal recovery after browser restart.

This suite does not yet simulate process termination mid-transaction, quota exhaustion, account-switch UI behavior, or network recovery. Those remain required before importer integration.
