# Character Library cloud backup protocol

Status: design contract for the feature branch. No browser importer is enabled by this document.

## Non-destructive rule

The browser-local library remains the source of truth until every passport and every reference image has passed cloud read-back verification. A partial backup is not a successful backup. Never delete or rewrite the original localStorage passport or IndexedDB Blob during backup, retry, cancellation, conflict, or rollback. Cloud cleanup is a separate explicit operation and is not part of import rollback.

## Required local backup journal

Before the first network request, create a separate journal entry keyed by the authenticated owner and local character UUID. Do not put progress fields into the canonical local passport. The journal must record:

- local character UUID and eventual cloud character UUID;
- canonical metadata fingerprint for the passport payload;
- for each local reference UUID: SHA-256, byte size, MIME type, filename, deterministic/persisted idempotency key, eventual cloud asset UUID, state, last error category, and last verified timestamp;
- protocol version and journal update time.

Persist the journal before sending a request. Read it back and verify it before proceeding. The journal is recoverable metadata, not a replacement for the source passport or image Blobs.

## State machine

Each reference follows only these states:

1. `local_only`: source Blob exists in IndexedDB; no cloud reservation known.
2. `reserved`: upload request has returned an asset ID or the deterministic key is known and the server reservation is being reconciled.
3. `upload_pending`: server status is `pending_upload`; retry may use the same key and exact same bytes.
4. `object_uploaded`: Storage upload returned, but independent verification is not complete. Never count as backed up.
5. `verified`: server status is `ready`, authenticated content read-back succeeded, and cloud SHA-256/size/dimensions match the local Blob.
6. `retryable_error`: transient network/Storage/worker issue. Keep source bytes and journal; resume with the same idempotency key and unchanged content.
7. `conflict`: server reports a different fingerprint for the same key or local/cloud identity. Stop automatic retry; do not overwrite either copy.
8. `terminal_error`: invalid image or terminal server lifecycle state. Keep local source; require explicit user repair or a new reference version.

Allowed forward progress: `local_only → reserved → upload_pending → object_uploaded → verified`. Retries may move among the pending states. A fingerprint conflict never transitions to verified.

## Metadata import

- Send the existing local character UUID as `source_local_id`; never use it as the cloud primary key.
- Use the authenticated character create API. Exact replay returns the same cloud character; changed passport data for the same owner/local UUID returns conflict and never overwrites.
- Persist the returned cloud character UUID in the journal and read the cloud passport back through the authenticated owner-scoped GET route.
- Compare the canonical fields and reference descriptors before starting image uploads.
- Guest libraries remain local-only; never create cloud records without an authenticated owner session.

## Image upload and recovery

- One request per reference, maximum six references per local character, each at most 8 MiB.
- Generate and persist a distinct Idempotency-Key before the request. Reuse that key only with identical bytes, filename, MIME type, and character identity. A changed image is a new reference version with a new key; never overwrite the old object.
- The server owns the bucket, object key, asset ID, and outbox event. The browser sends only the file and idempotency key.
- After upload, poll `GET /api/characters/{character_id}/references`. Only an owner-matched asset with status `ready` is eligible for read-back. `object_uploaded` is not success.
- Fetch `GET /api/media/{asset_id}/content` using the authenticated session. The server revalidates the stored reservation fingerprint and returns `X-Content-SHA256`. The client must independently hash the returned bytes and compare the bytes/hash, size, MIME type, width, and height against the local IndexedDB Blob.
- Persist `verified` in the journal only after all comparisons pass. Then read the journal back and verify the persisted mapping.

## Retry, cancellation, and rollback

- A lost response is an uncertain outcome, not a failure proof. Reconcile with the same key and status endpoint before generating another key.
- Transient errors preserve the exact key and local Blob. Never blindly create a second upload.
- A 409 fingerprint conflict is terminal for that key. Do not change the source Blob or overwrite the cloud asset to make the conflict disappear.
- If the user cancels, stop scheduling new requests; allow already-reserved server work to finish/reconcile. Keep all local data and the journal.
- Rollback means abandoning or resuming the journal, not deleting local or cloud data. Any cloud cleanup requires a separately reviewed, explicit user action through the existing fenced cleanup/outbox lifecycle.
- Never remove local passport or Blob data automatically, even after all references are verified. Local cleanup is a separate future feature with explicit confirmation and a recoverable grace period.

## Completion criteria

A character backup is complete only when:
- cloud passport identity and metadata read back exactly;
- every local reference has exactly one persisted cloud asset mapping;
- every mapped asset is `ready`;
- every image has passed authenticated byte-for-byte read-back fingerprint comparison;
- the local journal has been read back and all entries are `verified`;
- no source localStorage record or IndexedDB Blob was modified or removed.

No frontend import button should be enabled until browser tests cover interrupted uploads, lost responses, duplicate taps, changed bytes, foreign-owner attempts, worker delay/dead-letter, read-back mismatch, offline resume, cancellation, and storage quota failure.
