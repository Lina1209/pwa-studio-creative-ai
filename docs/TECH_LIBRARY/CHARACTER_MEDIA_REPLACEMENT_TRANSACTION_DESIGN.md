# Character Media Replacement Transaction Design

Status: design only; not wired to the application or production.

## 1. Purpose and safety invariant

Replace one character reference image without creating a period in which the character loses its last known-good image.

The governing invariant is:

> The currently referenced asset remains readable until a different asset has been uploaded, independently verified as `ready`, and atomically made current. The previous asset is eligible for cleanup only after the pointer/manifest switch commits.

A failed upload, verification, authorization check, optimistic-version check, or transaction must leave the old reference intact. No browser code may delete Storage objects or call service-role cleanup RPCs.

## 2. Identity model

- A cloud media asset is immutable after reservation: its bytes, SHA-256, size, MIME type, owner, character, and local reference identity are bound.
- A changed image MUST receive a new local reference identity. Reusing the old `local_reference_id` with different bytes is rejected by the existing identity binding and must remain rejected.
- The replacement request identifies the old current asset and the new ready asset explicitly. It must not infer identity from a filename or array position.
- Both assets must belong to the authenticated owner and the same character. The new asset must be `ready`; the old asset must still be the expected current asset.

## 3. Required lifecycle

### Phase A — stage new media

1. Authenticate the caller and resolve the owned character server-side.
2. Reserve/upload the changed image under a NEW local reference ID and idempotency key.
3. Verify the stored object through the existing media verification pipeline.
4. Wait until the media catalog reports `ready`; compare asset ID, character ID, local reference ID, SHA-256, byte size, and MIME type.
5. Do not mutate the active character manifest or request cleanup for the old asset during this phase.

If any step fails, retain the old current asset. A newly uploaded but unreferenced asset may remain for later reconciliation; do not eagerly delete it.

### Phase B — atomic switch

Provide a server-only authenticated replacement operation backed by one database transaction/RPC. Its input should include:

- authenticated owner (derived from the session, never trusted from request JSON);
- character ID;
- expected character/manifest version;
- stable reference slot/key being replaced;
- expected old asset ID;
- new asset ID and new local reference ID;
- expected new asset fingerprint (SHA-256, size, MIME).

Within the transaction, in a consistent lock order:

1. Lock the owned character row and validate that cleanup has not been requested.
2. Validate the expected version and that the slot still points to the expected old asset. A stale version or changed pointer returns a conflict without changing either asset.
3. Lock both media rows in deterministic asset-ID order.
4. Validate same owner and character, old asset is the current referenced asset and is in an allowed live state, new asset is `ready`, and its immutable fingerprint matches the request.
5. Update the manifest/reference slot to the new asset and increment the character version exactly once.
6. Only after the reference no longer points to the old asset, mark the old asset `cleanup_pending` and insert the canonical cleanup outbox event in the SAME transaction.
7. Commit. The cleanup worker later claims and deletes the old Storage object, then finalizes metadata. The browser never performs Storage deletion.

The implementation must follow the repository's established character-version RPC and media cleanup locking conventions. Do not introduce a second, weaker reference representation or bypass the existing reference guard.

## 4. Failure and retry semantics

- Upload retry with identical bytes and identity: same idempotency key, same reservation/asset.
- Changed bytes: new local reference identity and new idempotency key.
- Upload/verification failure: old pointer unchanged.
- New asset not `ready`: switch rejected.
- Expected version or old pointer mismatch: conflict (409); old pointer and old asset unchanged. Keep the new ready asset for explicit reconciliation; do not automatically delete it.
- Transaction rollback: manifest, old asset state, and outbox remain unchanged.
- Lost response after successful commit: retry must be idempotent. The operation should persist or derive a replacement operation identity so a retry can return the already-committed result rather than switching twice.
- Cleanup retry/dead-letter: new asset remains current and readable; old asset remains tombstoned/cleanup-pending and is never reattached automatically.
- Account switch during a client workflow: stop subsequent client steps using the existing owner/context-version fence. Server authorization remains authoritative.

## 5. Concurrency requirements

Add disposable-PostgreSQL two-session tests for:

1. Two replacements racing from the same expected version: exactly one commits; the other conflicts.
2. Replacement racing character cleanup: either cleanup intent wins and replacement is rejected, or replacement commits first and cleanup observes the new manifest; no dangling current pointer.
3. Replacement racing a second manifest edit: optimistic versioning prevents lost updates.
4. Replacement racing old-asset cleanup: cleanup must not claim/delete an asset that is still referenced; after atomic switch it may be claimed.
5. Two identical retries: one logical replacement and one cleanup outbox event.
6. New asset becoming non-ready or fingerprint mismatch before transaction: reject with no pointer change.
7. Cross-owner and cross-character asset substitution: reject before manifest mutation.
8. Transaction failure between manifest update and outbox insertion: rollback both changes.
9. Lost-response retry after commit: return the committed result without duplicate outbox events.
10. Cleanup worker failure/dead-letter after switch: new pointer remains healthy and old tombstone remains auditable.

All race tests must run only against disposable CI PostgreSQL, never the live Supabase project.

## 6. API and authorization boundary

The future API route should:
- require a valid authenticated bearer token;
- derive owner identity from the verified session;
- validate UUIDs and request shape;
- reject foreign characters/assets without revealing their existence;
- call one narrow server-side transaction operation;
- return the committed character version and replacement status;
- use private/no-store response headers;
- never expose service-role credentials or signed Storage deletion authority to the browser.

No user-facing DELETE route should be introduced as a shortcut for replacement. No client-side Storage DELETE and no direct browser RPC to cleanup functions.

## 7. Rollout gates

Do not connect this design to UI until all gates pass:

- migration/RPC reviewed for grants, RLS interaction, immutable identity constraints, deterministic lock ordering, and rollback behavior;
- backend route tests cover auth, ownership, validation, conflicts, idempotency, and no Storage deletion;
- disposable PostgreSQL transaction and concurrency tests pass;
- cleanup outbox integration proves old media is queued only after the pointer switch;
- frontend adapter tests prove account/context fencing and stale-version handling;
- explicit read-only review confirms no production schema, secrets, Render service, or live Supabase changes.

A separate approval is required before any production migration, deployment, or live-data operation.

## 8. Current implementation boundary

The repository currently has immutable media upload identity, upload verification, a local backup coordinator, a pure replacement planning service, and cleanup outbox infrastructure. These pieces do NOT yet constitute an end-to-end cloud replacement feature. The user-facing atomic replacement route/RPC and UI integration remain future work.

This document records the required contract only. It does not claim that replacement is implemented.
