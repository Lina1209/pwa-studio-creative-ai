# Character media backup orchestration design

## Status

Design only. This document does not connect the media transfer adapter to the backup button, perform uploads, change the restore flow, or modify production services.

## Current building blocks

- The local character library stores owner-scoped metadata in localStorage and image Blobs in IndexedDB.
- `PWAStudioCharacterRestoreBridge.getLocalImageBlob(referenceId, ownerId, version)` reads a Blob only for a valid current owner context and checks the context again after the asynchronous IndexedDB read.
- `PWACharacterMediaTransfer` provides authenticated upload, content download, and server-side readiness polling with SHA-256/fingerprint checks.
- `PWACharacterMediaBackupCoordinator.backupCharacterMedia` uploads references serially and validates the upload acknowledgement and exact `ready` result.
- Cloud character rows are mapped to local rows by `source_local_id` and carry an optimistic `version`.

## Required orchestration order

1. Capture `ownerId` and `contextVersion`. Build a closure that calls the bridge's `isCurrent(ownerId, contextVersion)`; do not pass a stale or unbound `isCurrent` method.
2. Read and validate the complete local library. Refuse malformed, duplicate, or over-limit data before any remote write.
3. Read all cloud character pages using bounded pagination. Validate unique `source_local_id` mappings and cloud IDs.
4. Create or update character passport metadata without publishing local-only image reference IDs as if they were cloud asset IDs. Preserve any already verified cloud manifest entries.
5. For each local image, use the bridge's owner-scoped Blob reader and the existing transfer adapter. Keep uploads serial and bounded. Require exact character ID, local reference ID, content digest, byte size, MIME type, and final `ready` status.
6. Only after every image intended for that passport has reached the verified `ready` state, construct the cloud manifest from server-acknowledged asset IDs and fingerprints.
7. PATCH the passport manifest with the latest cloud `version` as `expected_version`. Read back and validate the returned passport ID and incremented version.
8. If a version conflict (409) occurs, stop. Never blindly retry with a new version, overwrite concurrent edits, or delete the old asset. Require a fresh read and explicit conflict resolution.
9. Re-check account context before and after every awaited remote operation and before any local UI/state update. If the account changes, stop immediately and do not continue using the captured session.
10. Report partial progress accurately. A verified upload that is not yet referenced by the passport is not a completed backup. Do not claim the entire library is backed up.

## Idempotency and recovery requirements before activation

- The same local reference must map to a stable idempotency identity across retries; a retry must not create duplicate cloud assets.
- The server must reject reuse of an idempotency key with different bytes or metadata.
- A retry must first reconcile existing cloud references/assets for the same owner, character, and local reference ID before uploading again.
- Partial success must be resumable without overwriting an already verified asset or losing a prior manifest.
- If a cloud upload succeeds but the passport manifest PATCH fails, keep the verified asset intact and make the next run reconcile it. Do not invoke cleanup from the browser.
- A failed or timed-out readiness poll must not be represented as success. Reconciliation must use the authenticated owner-scoped catalog endpoint.
- No global access token may be exposed through the window bridge. The transfer adapter must obtain credentials through a private closure inside the app scope.

## Required tests before wiring the button

1. Owner A cannot read owner B's IndexedDB Blob.
2. Invalid owner, invalid reference ID, missing Blob, and malformed Blob fail closed.
3. Account switch before IndexedDB read, during read, and immediately after read prevents upload.
4. Local-to-cloud character mapping mismatch prevents upload.
5. Exact upload acknowledgement and exact `ready` fingerprint are required.
6. A repeated run reconciles the same asset and does not create a duplicate.
7. Partial upload followed by retry completes without changing already verified assets.
8. Passport PATCH uses the current expected version and preserves unrelated manifest entries.
9. A 409 conflict stops without retrying, overwriting, or deleting assets.
10. Account switch during pagination, upload, readiness polling, or manifest PATCH prevents further writes and UI updates.
11. The backup button reports partial vs complete outcomes truthfully.
12. The restore binary pipeline remains separate: download and stage all Blobs, verify all fingerprints, then activate atomically with rollback on failure.

## Activation gate

Do not connect this orchestration to the user-facing backup button until the idempotency/reconciliation behavior and all tests above are implemented and passing. Do not add a browser-facing delete path or call service-role cleanup RPCs from the client. Production rollout, migrations, worker deployment, and provider calls are outside this feature-branch task.
