# PWA Studio — PostgreSQL design for the private media outbox

**Status:** design only. This is not an executable migration and has not been run against any database.
**Purpose:** make media metadata changes and background work requests atomic, then deliver work safely at least once.
**Activation:** blocked until the schema is reconciled against the disposable Supabase schema, RPCs are reviewed, and multi-session concurrency tests pass.

## 1. Core invariant

A media state transition that requires asynchronous work and its outbox event MUST commit in one PostgreSQL transaction. There must be no state in which a pending upload/cleanup is committed but its corresponding event is absent, or an event exists for a metadata mutation that rolled back.

Do not implement this as two independent HTTP requests or two REST calls. Use one server-only Postgres RPC / transaction.

## 2. Proposed outbox record

A future `media_asset_outbox` table should contain:

- `id`: UUID primary key.
- `owner_id`: UUID, same owner as the referenced media asset.
- `asset_id`: UUID foreign key to `media_assets(id)`.
- `event_type`: closed allowlist: `media_upload_verify_requested`, `media_cleanup_requested`.
- `operation_id`: UUID for the logical upload/replacement/delete operation.
- `idempotency_key`: opaque bounded string; unique per owner.
- `status`: `pending`, `claimed`, `delivered`, `dead_letter`.
- `available_at`, `claim_token`, `claim_expires_at`, `attempts`, `max_attempts`, `created_at`, `delivered_at`.
- A unique constraint on `(owner_id, idempotency_key)`; a second unique constraint on `(asset_id, operation_id, event_type)`.

No file bytes, raw storage path, bucket supplied by the client, signed URL, JWT, service-role key, or provider credential belongs in the outbox. The worker receives only opaque IDs and resolves trusted bucket/path values from owner-filtered database metadata.

## 3. Atomic create pattern

The future server-only RPC should validate the authenticated owner and all association links, insert a `media_assets` row in `pending_upload`, and insert its `media_upload_verify_requested` event before returning. Both inserts happen inside the same function transaction. If either insert fails, the entire call rolls back.

For cleanup, the same rule applies: mark the asset unavailable / `cleanup_pending` and insert the cleanup event in the same transaction. A repeated request with the same owner-scoped idempotency key must return the original operation only when its immutable request fingerprint matches; reuse with a different asset or operation must fail with a conflict. Never create a second event for the same operation.

This repository's current `media_assets` draft schema does not yet contain the final status/version/operation columns. Do not copy/paste an RPC or apply a migration until those columns and all existing constraints have been reconciled against the exact disposable database schema.

## 4. Safe worker claim

A worker claims a small batch in one transaction. The production SQL shape should be equivalent to:

```sql
with candidates as (
  select id
  from public.media_asset_outbox
  where status = 'pending'
    and available_at <= now()
  order by available_at, created_at
  for update skip locked
  limit 20
)
update public.media_asset_outbox as event
set status = 'claimed',
    claim_token = gen_random_uuid(),
    claim_expires_at = now() + interval '90 seconds',
    attempts = attempts + 1
from candidates
where event.id = candidates.id
returning event.id, event.owner_id, event.asset_id,
          event.event_type, event.operation_id, event.claim_token;
```

This is a design sketch, not a ready-to-run migration fragment. In particular, claim-token generation, max-attempt handling, row-level permissions, and indexes must be tested against the selected PostgreSQL version.

## 5. Fenced completion and retry

Every worker write must be conditional on all of:

- event ID;
- exact claim token issued to that worker;
- `status = 'claimed'`;
- claim expiry later than the database's current time.

Acknowledge with a single conditional update that sets `delivered`, clears the claim, and records `delivered_at`. If zero rows are updated, the worker has lost its lease and MUST NOT attempt another state mutation.

Retry uses the same fence, clears the claim, returns to `pending`, and sets a bounded `available_at` delay. When attempts reach `max_attempts`, move to `dead_letter` and raise an operational alert. An expired claim may be recovered only after its expiry; a subsequent claim must issue a new token. Old workers must fail their conditional writes.

The Python lifecycle model in `backend/app/services/media_outbox.py` mirrors these transitions. It is pure logic and does not provide database-level locking or durability.

## 6. Side-effect ordering

### Upload verification
1. Claim event.
2. Reload media row by both asset ID and owner ID.
3. Resolve immutable object key from trusted metadata.
4. Verify object existence, bucket, size and content metadata.
5. Conditionally transition the asset to `ready` using row version + operation ID.
6. Acknowledge the event with the claim token.

If the worker crashes between steps 5 and 6, the redelivered event must detect that the same operation is already complete and acknowledge idempotently.

### Cleanup
1. Claim event.
2. Reload owner-scoped asset metadata.
3. Re-check exact bucket + object-key references at the serialization boundary immediately before deletion.
4. If referenced, do not delete; mark the operation for investigation/reconciliation.
5. Delete the exact immutable object key.
6. Confirm deletion / absence, finalize the tombstone conditionally, then acknowledge.

If Storage returns an ambiguous outcome, reconcile object existence before retrying. Never infer success from a timeout. Never accept the object path from the event payload or browser.

## 7. Database security and operations

- Enable RLS; deny browser access to the outbox entirely.
- Revoke all table privileges from `anon` and `authenticated`; grant only the minimum required to a narrowly scoped service role / SECURITY DEFINER RPC.
- SECURITY DEFINER functions must set a fixed safe `search_path`, validate inputs, and be executable only by the backend role.
- Do not trust a client-supplied `owner_id`; derive it from the verified JWT in the API and pass it only through the server boundary.
- Add indexes for pending-event claim order, expired claims, and owner/idempotency uniqueness.
- Monitor oldest pending age, retry counts, dead-letter count, expired claims, and cleanup backlog. Logs contain opaque IDs and safe error codes only.

## 8. Required verification before activation

1. Create two disposable Auth users and verify cross-owner event/asset association is impossible.
2. Force the asset insert to succeed and outbox insert to fail; confirm the transaction leaves neither row.
3. Force the outbox insert to succeed and asset mutation to fail; confirm the transaction leaves neither mutation nor event.
4. Submit the same idempotency key twice with the same fingerprint; confirm one operation and one event.
5. Reuse the key with a different fingerprint; confirm conflict.
6. Run two concurrent workers; confirm `SKIP LOCKED` prevents duplicate active claims.
7. Expire worker A's lease, let worker B reclaim, and prove A cannot acknowledge or mutate after B's claim.
8. Crash after the Storage side effect but before acknowledgement; prove redelivery is safe and idempotent.
9. Verify dead-letter behavior, retry bounds, and operational alerting.
10. Verify no browser role can read or write the outbox.

No migration, RPC, worker, scheduler, or Storage call is implemented by this document.
