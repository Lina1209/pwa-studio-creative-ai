# PWA Studio — private media cleanup operator runbook

**Status:** design/runbook only. No operator recovery command or admin API is implemented.
**Scope:** dead-lettered character-reference cleanup events from draft migration 0019.
**Environment rule:** use a disposable Supabase project only until the full Auth/RLS/Storage acceptance matrix passes. Never use this runbook as permission to inspect or mutate production.

## 1. What dead-letter means

A cleanup event enters `dead_letter` after its bounded retry budget is exhausted, or when the database detects an invalid/missing asset, a changed character cleanup operation, or a surviving reference. The associated media row is intentionally retained as `cleanup_pending`; the character remains present with its cleanup-operation marker. This is a safety tombstone, not proof that the Storage object was deleted.

Do not manually mark the asset `deleted`, detach it from the character, delete the character, or mark the event `delivered`. Those changes would bypass the Storage side effect and the fenced database acknowledgement.

## 2. Triage checklist

For a future authorized operator tool, collect only the following server-side facts:

- event UUID, event type, status, attempt count, maximum attempts, and last safe error category;
- media asset UUID, owner UUID, lifecycle status, bucket, and immutable object key;
- character UUID and whether its `cleanup_operation_id` matches the event's `operation_id`;
- whether another media row, metadata field, or character passport still references the exact bucket + object key;
- whether the object exists in the private Storage bucket, checked with a server-only credential.

Never ask an operator to paste service-role credentials, signed URLs, raw image bytes, or user tokens into a ticket or chat. Do not expose object paths in ordinary application logs.

## 3. Decision rules

1. **Reference still exists:** do not delete or requeue. Resolve the reference through a separately reviewed owner-scoped workflow, then repeat the full reference scan.
2. **Character operation does not match:** stop. Treat it as inconsistent state and investigate; do not rewrite the operation marker.
3. **Object is already absent:** an authorized recovery worker may safely repeat the idempotent DELETE (404 is success) and then complete with a fresh claim token.
4. **Object exists and no reference survives:** an authorized recovery worker may requeue the same immutable event for a fresh claim, after validating the exact bucket/path against the canonical character-reference key.
5. **Storage result is ambiguous (timeout/connection loss):** do not mark complete. Retry the same immutable key after lease/retry rules; never invent a new object key.
6. **Malformed path, unsupported bucket, or missing metadata:** stop and preserve the tombstone for manual investigation.

## 4. Required future recovery API

Before operators can safely requeue dead letters, implement a dedicated service-role-only RPC or narrowly scoped admin service that:

- accepts event UUID and an operator/audit actor derived from a verified admin session (never a client-supplied owner or path);
- locks the event, asset, and cleanup character in deterministic order;
- requires `dead_letter`, `cleanup_pending`, matching owner/asset/operation IDs, and the canonical `studio-media/<owner>/characters/<character>/<object>.(png|jpg|webp)` identity;
- repeats exact-reference checks and refuses in-flight upload states;
- records an immutable audit event with actor, reason code, prior/new attempt count, and timestamp;
- resets only the retry scheduling/claim fields, never the object identity, asset status, or operation identity;
- returns a safe result without exposing service credentials or signed URLs;
- is covered by transaction, authorization, stale-token, and race tests before any deployment.

No such RPC, admin screen, or command exists today. Until it is implemented and reviewed, the correct response to a dead-letter event is to preserve it and escalate for engineering investigation—not to edit rows manually.

## 5. Verification boundary

The current migration and worker are feature-branch drafts. Disposable PostgreSQL CI covers transaction rollback, claim races, reference races, and batch processing. It does not run real Supabase Auth/RLS JWT sessions or real Storage requests. The worker crash-window unit test is authored, but its latest commit has not yet been confirmed by CI. No cleanup worker is deployed and no production object has been deleted.
