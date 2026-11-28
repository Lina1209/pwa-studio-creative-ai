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
- expected new asset fingerprint (SHA-256, size, MIME);
- a stable replacement operation/idempotency ID so a lost-response retry returns the committed result and cannot create a second cleanup event.

Within the transaction, in a consistent lock order:

1. Lock the owned character row and validate that cleanup has not been requested.
2. Validate the expected version and that the slot still points to the expected old asset. A stale version or changed pointer returns a conflict without changing either asset.
3. Lock both media rows in deterministic asset-ID order.
4. Validate same owner and character, old asset is the current referenced asset and is in an allowed live state, new asset is `ready`, and its immutable fingerprint matches the request.
5. Update the manifest/reference slot to the new asset and increment the character version exactly once.
6. Only after the reference no longer points to the old asset, mark the old asset `cleanup_pending` and insert exactly one replacement-scoped outbox event in the SAME transaction.
7. Commit. The cleanup worker later claims and deletes the old Storage object, then finalizes metadata. The browser never performs Storage deletion.

The implementation must be a NEW replacement-specific server-only RPC/transaction. The existing `pwa_update_character_versioned` updates the character manifest/version but does not also tombstone a media asset and enqueue cleanup; calling it separately from cleanup would create an unsafe split transaction. The existing `pwa_request_character_media_cleanup` is a WHOLE-CHARACTER deletion workflow, not a single-reference cleanup API, and must not be repurposed for replacement. The new RPC must update the manifest, old asset status, and outbox row atomically while following the established character-version and media cleanup locking conventions. Do not introduce a second, weaker reference representation or bypass the existing reference guard.


## 4A. Replacement cleanup is a distinct worker scope

The existing cleanup outbox is NOT directly reusable for a single-reference replacement:

- The current `media_cleanup_requested` claim path requires the character's `cleanup_operation_id` to equal the outbox operation ID. That flag represents whole-character deletion.
- The existing completion path also requires that same whole-character cleanup intent.
- The existing `pwa_request_character_media_cleanup` RPC tombstones the complete character asset set and sets the character deletion intent. It must never be called for replacing one image.

Therefore a replacement must use a distinct event type, for example `media_reference_replacement_cleanup_requested`, and a distinct operation scope. The feature migration must extend the outbox event-type constraint and update the cleanup worker's claim/completion logic (or add narrowly scoped replacement claim/completion RPCs) so that:

1. The event is eligible only when its asset is `cleanup_pending`, belongs to the owner and character, and its replacement operation is recorded.
2. The character itself is still present and is NOT required to have `cleanup_operation_id` set.
3. Before returning a Storage key, the claim transaction rechecks that no character passport, other media metadata, or other media row references the exact old object key. A surviving reference must fail closed and go to an auditable non-deleting state.
4. Completion is fenced by event ID, owner, asset ID, operation ID, and claim token; it may mark the old asset `deleted` and detach it only after the worker confirms DELETE/404.
5. Whole-character deletion events retain their existing stricter `cleanup_operation_id` checks and behavior. The two scopes must not be conflated.

The pure outbox model and cleanup repository/worker allowlists must also recognize the new event type. Until this is implemented and race-tested, the replacement transaction must NOT enqueue the existing whole-character cleanup event and must NOT attempt to delete the old object.

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
11. Replacement RPC must reject any new asset still in `object_uploaded`, even when its object exists in Storage; only the verification worker may transition it to `ready`.
12. Replacement cleanup claim/completion must be isolated from whole-character deletion intent; the existing worker's `media_cleanup_requested` contract cannot process a replacement-scoped event as-is.

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

The repository currently has immutable media upload identity, upload verification, a local backup coordinator, a pure replacement planning service, and cleanup outbox infrastructure. The pure planner now requires the new asset to already be `ready`; it does not perform the state transition. The existing versioned character RPC and whole-character cleanup RPC cannot safely be composed to replace one image. These pieces do NOT yet constitute an end-to-end cloud replacement feature. The user-facing atomic replacement route/RPC and UI integration remain future work.

This document records the required contract only. It does not claim that replacement is implemented.


## 9. Verified manifest-to-asset mapping and identity gap

A read-only inspection of the current frontend, upload API, and identity migration confirmed an important gap that must be resolved before implementing the replacement RPC:

- The character passport currently stores `reference_data.referenceImages[]` entries with `id`, `name`, and `type`. The frontend's backup serializer copies those three fields; it does not store a cloud `asset_id`.
- The upload API accepts `local_reference_id` and returns an explicit mapping containing `asset.id`, `asset.character_id`, and `asset.local_reference_id`.
- Migration `0025_character_reference_identity_binding.sql` binds `media_assets.local_reference_id` to one immutable asset per owner/character. Reusing that identity for changed bytes is intentionally rejected.
- The current UI generates a new composite reference ID for every newly selected file and uses that same value as the local IndexedDB image key and the manifest entry's `id`.
- The owner-scoped media catalog can therefore resolve a manifest entry to its cloud asset by matching the entry's current `id` to `media_assets.local_reference_id`; it must not guess from array position, filename, or a client-supplied asset ID.

This means the current `id` conflates two concepts: the logical reference slot shown in the character passport, and the immutable identity of the uploaded bytes. A changed image needs a new `local_reference_id`, but a replacement should preserve the logical slot. The current manifest has no separate field for those concepts.

### Required additive manifest v2 contract

Before the atomic replacement RPC is implemented, introduce a backward-compatible manifest representation with two distinct identifiers:

```json
{
  "slot_id": "stable-logical-reference-id",
  "asset_local_reference_id": "immutable-upload-identity",
  "name": "Reference name",
  "type": "image/jpeg"
}
```

Rules:

1. `slot_id` identifies the logical reference in the character passport and remains stable when its image changes.
2. `asset_local_reference_id` identifies the immutable upload and must match exactly one `media_assets.local_reference_id` for the same owner and character.
3. For a legacy entry containing only `id`, interpret that value as both the initial `slot_id` and the current `asset_local_reference_id`. Do not rewrite legacy rows as a side effect of reading them.
4. A replacement keeps `slot_id`, assigns a fresh `asset_local_reference_id`, and changes only that slot's asset binding and permitted display metadata.
5. The catalog response remains the authoritative source of cloud `asset_id`, lifecycle state, and verified fingerprint. The manifest must not become a second source of truth for those fields.
6. Reject duplicate slot IDs, duplicate asset-local-reference bindings within one passport, missing catalog matches, ambiguous matches, cross-character matches, and a new identity already bound to another asset.
7. The initial migration path must be additive and preserve old clients' ability to read legacy `id` entries. Any write that upgrades an entry must be version-checked and tested for round-trip compatibility.

### Replacement RPC identity contract

The future RPC should identify the target by `slot_id`, the expected old `asset_local_reference_id`, and the new `asset_local_reference_id`. It should resolve and lock the old/new `media_assets` rows server-side using the authenticated owner and character. The RPC must independently verify:

- exactly one target slot exists and still points to the expected old local-reference identity;
- exactly one old asset and one new asset match their respective local-reference identities for that owner and character;
- the old asset is still live and is not already tombstoned;
- the new asset is `ready` and its stored fingerprint is the one verified by the upload verifier;
- no other passport slot or metadata reference still points to the old object before scheduling its deletion.

The client must not choose a raw Storage path or supply authority to delete an object. The RPC returns a conflict if the slot binding or character version changed. The old pointer and old object remain intact on every rejected or rolled-back attempt.

## 10. Implementation boundary after this audit

The repository currently supports upload reservation, immutable local-reference binding, independent verification, and owner-scoped catalog lookup. It does not yet support a logical slot identity distinct from the immutable upload identity, nor does the current passport serializer persist a cloud asset ID.

Consequently, the next implementation must first add and test the manifest v2 compatibility layer and catalog-to-manifest resolver. Only after that contract is stable should a new migration add the atomic replacement RPC and replacement-specific cleanup event/claim/completion path. Do not wire the current `id` field directly to a destructive replacement operation.
