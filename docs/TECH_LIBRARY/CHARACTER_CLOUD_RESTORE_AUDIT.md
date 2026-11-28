# Character cloud restore and synchronization audit

Date: 2026-11-28
Status: feature-branch implementation checkpoint. No importer activation, production migration, Storage operation, or deployment.

## Confirmed server-side protections

- Cloud character creation uses `pwa_create_character_idempotent` with the authenticated owner derived by the API. A unique `(owner_id, source_local_id)` mapping prevents duplicate cloud identities for the same local character within one account.
- Repeating creation with the same local ID and identical passport returns the existing mapping; reusing that ID with changed passport data fails closed with a conflict. An in-progress cleanup also blocks re-import.
- Character reference uploads reserve a media row and durable verification outbox event before Storage upload. The reservation binds owner, character, object path, size, MIME, SHA-256, and dimensions.
- Upload retries use an idempotency key and immutable operation/fingerprint checks. A duplicate object conflict does not mark the upload as complete.
- A verification worker independently downloads and decodes the private object and compares digest, byte size, MIME, and dimensions before marking the asset ready. Claim-token fencing prevents a stale worker from completing another worker's lease.
- Private media reads require ready status, owner match, private bucket, and exact Storage path binding to the linked character/project ID. Signed URLs are short-lived; direct proxy reads are bounded.
- Character cleanup uses a durable outbox, locks the complete child asset set, checks references, and does not race deletion against pending uploads or verification.

## Important integration boundaries

- The browser backup journal remains an isolated IndexedDB module and is not loaded by the product UI.
- The API worker scripts exist, but current Render configuration starts only the API web process. Queue processing is not proven operational until separate private worker services are deliberately provisioned and monitored.
- The character list now has owner-scoped keyset pagination (maximum 100 per page), with an owner-bound signed cursor and immutable ordering. The client must still traverse until `next_cursor = null` and treat any failed page as incomplete.
- Character passport PATCH now requires `expected_version`; the compare-and-swap path increments a monotonic version and returns a conflict for stale writes. The create idempotency mapping remains a retry contract, not an update protocol.
- The journal's local `passportFingerprint` and reference SHA values must be recomputed from the actual source bytes before upload. Client-provided fingerprints are hints, not trusted verification.
- Before restore, the coordinator must fetch the canonical cloud passport and every required media status, download/read back each media object through the authenticated private-media API, and independently compare bytes/hash/size/MIME/dimensions. A `ready` status alone is not sufficient evidence that the browser's local copy matches.
- Restore must stage all data separately, verify the complete set, and only then offer an atomic local activation/swap. Never delete or mutate the old local passport/Blobs during a partial restore.
- Local and cloud IDs are distinct namespaces. Preserve the owner-scoped `source_local_id` mapping and never replace the cloud primary key with a browser-provided identifier.

## Newly implemented restore-planning boundary

- `character-cloud-restore.js` validates all cloud pages (up to 100 pages / 10,000 records), validates identity/version/timestamps/passport fields, rejects duplicate mappings, and creates a side-effect-free plan.
- The plan preserves local and cloud IDs separately, records missing-image metadata as a manifest without creating broken local image references, and classifies changed local/cloud records as conflicts rather than overwriting.
- Its guarded commit helper requires a complete conflict-free plan, unchanged local snapshot, owner match, account-current check, local limit compliance, and read-back verification through injected synchronous adapters.
- The restore planner is not loaded by `index.html` and is not connected to localStorage, IndexedDB, the backup journal, or a UI action. This is deliberate: no restore has been activated.
- CI run `46101439442` passed all three jobs on `b009d64`: backend unit tests, disposable PostgreSQL integration (including concurrency/cleanup stress harnesses), and real-browser IndexedDB journal/account-switch checks. The companion workflow `46101433709` also succeeded.
- The prior restore test failure on `6e0a206` was a malformed fixture that failed the representation validator before reaching the intended voice-type assertion; `b009d64` corrected the fixture and the newest full CI run passed.

## Resumable restore protocol design

- Added `docs/TECH_LIBRARY/CHARACTER_RESTORE_CHECKPOINT_PROTOCOL.md` (commit `7c5633a`) as a design-only specification for durable page checkpoints, owner-bound media staging, independent Blob read-back verification, atomic metadata activation, crash recovery, and lease-safe cleanup.
- The design explicitly accounts for the current split between owner-keyed localStorage metadata and the IndexedDB `images` object store: there is no cross-store transaction. It therefore stages and verifies Blobs first, then uses one localStorage key replacement as the activation point. Existing active records and Blobs remain untouched before activation.
- A recovery marker on newly restored records plus a canonical merged-library digest is required to distinguish a crash before metadata activation from a crash immediately after it. An unexpected current-library digest must stop for manual conflict handling, never trigger blind rollback.
- This is a protocol specification only. No runtime module, UI wiring, media download, schema change, or production operation was added. Restore/import remains disabled.

## Required acceptance matrix before importer activation

1. Retry create after a lost HTTP response; verify exactly one cloud character and stable mapping.
2. Reuse a local ID with modified passport; verify conflict and no overwrite.
3. Upload same image/key after lost response; verify one media asset and one object, with exact fingerprint match.
4. Reuse idempotency key with different bytes/metadata; verify conflict and no overwrite.
5. Crash between reservation, Storage upload, mark-uploaded, and verification; verify safe worker recovery without premature ready status.
6. Expire worker lease and race old/new workers; stale token must not complete.
7. Corrupt or replace remote bytes; verification must fail and asset must not become ready.
8. Test >100 characters and paginate until a stable complete snapshot is obtained.
9. Race two edits from separate sessions; one must receive a conflict rather than overwrite the newer version.
10. Interrupt restore at every stage; original local passport and image Blobs remain byte-for-byte unchanged.
11. Switch accounts during fetch/restore; late responses must not write into the newly active account.
12. Run against two disposable accounts and prove no cross-owner character, asset, or Storage access.

## Current decision

Keep cloud restore/import disabled. Versioned updates, paginated reads, a side-effect-free restore planner, and a guarded injected commit helper now exist on the feature branch. Remaining blockers include wiring the planner to the actual local storage adapters, durable resumable checkpoints, conflict-resolution UX, deletion/tombstone semantics, safe image transfer and validation, worker deployment/monitoring, and end-to-end browser interruption/account-switch tests. No production resources were touched.


## Media identity mapping gate (2026-11-28)

A source-level audit found that the current server API does **not** yet provide a provable mapping from a passport reference descriptor to a private media asset:

- Character `reference_data` stores reference descriptors with the local shape `{ id, name, type }`; the descriptor ID is a browser-local reference ID.
- `POST /api/characters/{character_id}/references` accepts an image plus an `Idempotency-Key`, but it does not accept or persist the browser reference ID. The asset ID is derived from the idempotency key and is a separate UUID namespace.
- `GET /api/characters/{character_id}/references` lists asset ID, character ID, file name/type, status, size, dimensions, and creation time. It does not return a local reference ID or the stored SHA-256.
- `GET /api/media/{asset_id}/content` returns verified bytes and an `X-Content-SHA256` response header, but the restore client still cannot determine which passport reference descriptor that asset belongs to.

Therefore, matching by filename, array order, MIME, dimensions, or image similarity would be unsafe and is explicitly prohibited. The existing planner's `referenceManifest` is descriptive metadata only; its `id` must not be treated as a cloud asset ID.

### Required contract before activation work

1. Extend the authenticated upload contract with a validated client reference UUID (or an equally strong immutable reference key) and persist it server-side on the media asset as an explicit association. Bind that association to the authenticated owner and exact cloud character in the same reservation transaction.
2. Make the character reference listing return an explicit mapping tuple: `local_reference_id`, `asset_id`, `character_id`, `status`, `file_name`, `file_type`, `size_bytes`, `content_sha256`, `width`, `height`. Keep owner, bucket, Storage path, metadata internals, and signed URLs private.
3. Reject duplicate local reference IDs per character and duplicate asset associations; enforce uniqueness/foreign keys in a reviewed migration and verify the behavior in disposable PostgreSQL only.
4. The restore planner must join only on that explicit mapping and compare the cloud passport descriptor to the mapped asset record. Require status `ready`, then independently verify downloaded bytes against SHA-256, byte size, MIME, width, and height.
5. Add route, repository, migration, cross-owner, duplicate, retry/idempotency, and browser end-to-end tests before enabling any activation path.

No migration, route, UI, worker, or production data was changed as part of this audit. Until this mapping contract exists, the media restore coordinator remains staging-only and local metadata activation remains blocked.
