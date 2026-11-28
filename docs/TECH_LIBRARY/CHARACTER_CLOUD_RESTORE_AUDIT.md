# Character cloud restore and synchronization audit

Date: 2026-11-28
Status: read-only review and implementation requirements. No importer activation, production migration, Storage operation, or deployment.

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
- The cloud character list currently requests at most 100 rows and has no cursor pagination. A restore flow must not silently treat a truncated list as complete.
- Character passport PATCH is owner-filtered, but the current repository update path has no expected-version/ETag precondition. Concurrent edits can be last-write-wins. Before enabling multi-device sync, add an atomic optimistic-concurrency contract (monotonic version or updated-at token) and a 409 conflict response; never silently overwrite a newer passport.
- The create idempotency mapping compares the full passport payload. This is appropriate for retrying an unchanged create, but it is not an update protocol. Changed local passports need an explicit versioned update path.
- The journal's local `passportFingerprint` and reference SHA values must be recomputed from the actual source bytes before upload. Client-provided fingerprints are hints, not trusted verification.
- Before restore, the coordinator must fetch the canonical cloud passport and every required media status, download/read back each media object through the authenticated private-media API, and independently compare bytes/hash/size/MIME/dimensions. A `ready` status alone is not sufficient evidence that the browser's local copy matches.
- Restore must stage all data separately, verify the complete set, and only then offer an atomic local activation/swap. Never delete or mutate the old local passport/Blobs during a partial restore.
- Local and cloud IDs are distinct namespaces. Preserve the owner-scoped `source_local_id` mapping and never replace the cloud primary key with a browser-provided identifier.

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

Keep cloud restore/import disabled. The underlying server-side identity and media lifecycle primitives are promising, but versioned concurrent updates, complete pagination, worker deployment/monitoring, end-to-end restore orchestration, and acceptance tests remain blockers. No production resources were touched.
