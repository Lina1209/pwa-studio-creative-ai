# Mini Cinema server-side concurrency and durable deletion design

Status: **design only; not a migration and not approved for production rollout**.
Prepared against PR #4 source on 2026-11-25. No live Supabase connection, SQL execution, schema change, deployment, or user-project mutation was performed.

## 1. Problem this design closes

The browser currently performs a timestamp preflight SELECT followed by a direct `projects.upsert()`. Those are separate requests. A second device can update or delete the same project between them. Browser-local tombstones cannot be observed by another device. Therefore the current implementation cannot guarantee that the newest edit wins or that a delete cannot be undone by a stale device.

Client timestamps remain useful for display and best-effort merge behavior, but they are not a concurrency authority. The authoritative state must be serialized in PostgreSQL.

## 2. Required database state

Additive columns on `public.projects`:

- `revision bigint NOT NULL DEFAULT 1`, constrained to be positive.
- `deleted_at timestamptz NULL`.

The revision is a server-owned, monotonically increasing integer for each project ID. It changes on every accepted mutation, including delete and explicit restore. Clients must never choose the next revision.

Existing rows are initialized at revision 1 and remain active (`deleted_at IS NULL`). A migration must not infer deletion from a missing browser-local tombstone.

The existing `owner_id` and `project_type` remain immutable identity boundaries for this contract. Mini Cinema operations are restricted to `project_type = 'movie'`.

## 3. Atomic operation contract

Expose one narrowly scoped authenticated database operation (or a backend endpoint that invokes an equivalent transaction). Do not accept an owner ID from the browser as authority; derive it from the verified caller identity (`auth.uid()` for a user-JWT RPC).

Input should contain:
- operation: `create | save | delete | restore`;
- project UUID;
- expected revision;
- the allowed project fields/payload for create/save/restore.

The transaction must lock the target row and validate identity, state, and expected revision before mutation.

### Create
- Require expected revision 0 and no existing project row with that UUID.
- Insert with the authenticated owner, `project_type='movie'`, revision 1, and `deleted_at=NULL`.
- A duplicate UUID is a conflict, not an overwrite.

### Save
- Require an existing row owned by the caller, `project_type='movie'`, `deleted_at IS NULL`, and exact expected revision.
- Update only the allowlisted mutable fields.
- Set revision to old revision + 1 and set `updated_at` using database time.
- If the expected revision is stale, make no changes and return a conflict containing the current revision (and only the caller's own row data if needed).

### Delete
- Require an active row and exact expected revision.
- Set `deleted_at` using database time and increment revision.
- Keep the row as a durable tombstone. Do not physically delete it during normal user deletion.
- Repeated delete requests with the same idempotency key return the original result; a different stale request returns conflict/already-deleted without reviving the row.

### Restore
- Restore is a distinct, explicit operation, never an ordinary save/upsert.
- Require a deleted row and exact current tombstone revision.
- Clear `deleted_at`, apply a validated restore payload, and increment revision.
- A stale device cannot restore a deleted project merely by uploading an older active copy.

All operations should accept an idempotency key scoped to caller + project + operation. Replaying the same key and same request returns the stored result; reusing it with different parameters is rejected. If durable idempotency is deferred, the operation must still be safe under retries by using the expected revision and returning the already-applied result where it can be unambiguously identified.

## 4. Security and privilege requirements

Preferred boundary: a small `SECURITY DEFINER` function called with the user's JWT, with all of the following:
- Derive caller identity inside the function from `auth.uid()`; reject NULL.
- Never accept `owner_id` as an input parameter.
- Fully qualify every table/function reference and set an empty `search_path`.
- Re-check owner and `project_type='movie'` in the transaction, not only in the frontend.
- Keep RLS enabled. Ensure SELECT policies continue to expose only the caller's own rows and active rows unless a specific owner-only tombstone lookup is required.
- Revoke EXECUTE from `PUBLIC`, `anon`, and any untrusted role; grant only to `authenticated`.
- Revoke direct INSERT/UPDATE/DELETE on `public.projects` from `authenticated` once every supported client is using the atomic operation. Keep only the minimum SELECT grant required by the read path.
- Ensure function ownership, table privileges, and RLS behavior are verified in a disposable PostgreSQL/Supabase environment. Do not assume SECURITY DEFINER automatically makes a function safe.

A service-role backend endpoint is an alternative, but it must derive the target user from the verified request principal and must not trust a caller-supplied user UUID. A service-role key must never be sent to the browser.

## 5. Frontend synchronization contract

Replace direct `.upsert(rows)` with the atomic operation:
- Track the last server revision alongside each locally cached project.
- Send that revision as `expected_revision` for save/delete/restore.
- On success, persist the returned canonical row and revision locally.
- On conflict, do not retry the stale payload automatically. Preserve the local draft separately, fetch the current active row/tombstone, and present a clear conflict choice (reload remote, keep a copy, or explicitly reconcile).
- On a deleted response, remove the project from the active list and retain a local display marker only as needed; the server tombstone is authoritative.
- Cloud loads must filter to active rows. A separate owner-scoped path may be used to detect a tombstone and explain why a stale local project is not being restored.
- Offline edits remain local drafts until the server accepts them. They must not be able to overwrite a newer server revision after reconnect.
- Keep current owner/auth-generation context checks and same-browser tombstone retry logic as defense in depth, not as the source of truth.

## 6. Compatibility and rollout gate

This change is not safe as a casual additive frontend patch. The current browser app writes directly to Supabase. If direct table writes remain granted, an older client can bypass the CAS function and resurrect or overwrite rows.

Required staged rollout:
1. Reconcile the live migration ledger and actual table/policy/function/grant state; repository migration filenames are not proof of what is deployed.
2. Build and test the new RPC and revision columns in a disposable environment cloned from the reconciled schema.
3. Deploy a compatible frontend/backend that can read revisions and use the atomic operation.
4. Verify adoption/compatibility for existing sessions and cached app versions.
5. Only at a controlled cutover, revoke authenticated direct table write privileges and verify the RPC path. Old clients should fail closed rather than silently fall back to direct upsert.
6. Run two-device staging tests and a rollback rehearsal before any production approval.

Do not add a production migration until the duplicate `0005` history is reconciled. The repository audit also records Storage policy replacement drift between `0002` and `0005`; it must be considered in the same migration-ledger reconciliation, even though it is not part of the project CAS mechanism.

## 7. Required disposable-database concurrency tests

Use two authenticated users (A and B), two independent sessions for A (A1/A2), and transaction barriers so the race ordering is deterministic.

| Scenario | Required result |
|---|---|
| A1 reads revision 4; A2 saves revision 5; A1 saves expected 4 | A1 receives conflict; revision 5 payload remains |
| A1 reads revision 4; A2 deletes to revision 5; A1 saves expected 4 | A1 receives deleted/stale conflict; tombstone remains |
| A1 deletes revision 4; A2 attempts save expected 4 | A2 cannot recreate row |
| A1 deletes to revision 5; A1 explicitly restores expected 5 | Active row returns at revision 6 |
| A1 restores expected 4 after delete at 5 | Conflict; tombstone remains |
| A1 retries the same accepted operation/idempotency key | Same result; revision does not increment twice |
| A1 reuses key with a different payload | Rejected |
| B attempts to save/delete/restore A's project UUID | No mutation and no disclosure of A's private payload |
| Anonymous caller invokes RPC | Denied |
| Authenticated caller attempts direct INSERT/UPDATE/DELETE after cutover | Permission denied |
| Two simultaneous saves both expect revision 7 | Exactly one succeeds; the other conflicts; final revision is 8 |
| A stale cached client reconnects after deletion | It cannot make the row active through ordinary save |

Also verify constraints, RLS, function EXECUTE grants, SECURITY DEFINER owner, empty search_path, and that no alternate write route bypasses the operation.

## 8. Current status

- Current frontend mitigations protect same-browser deletion/upsert races and fail closed for copy/restore while a local tombstone is pending.
- Cross-device correctness is **not yet guaranteed** because the current implementation still uses direct upsert and localStorage tombstones.
- This document is a contract/design artifact only. No SQL migration was authored or applied, no live schema was inspected, and no production setting was changed.
- Before implementation, complete the read-only live schema/migration-ledger reconciliation described in `docs/SUPABASE_SCHEMA_RECONCILIATION_AUDIT.md`.
