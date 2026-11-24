# Supabase RPC disposable-database test matrix

Date: 2026-11-25  
Status: test specification only. No database has been provisioned and no SQL has been executed.

## Why this file exists

The repository's current backend workflow runs Python tests but does not provision PostgreSQL or Supabase. Those tests cannot establish PostgreSQL locking, RLS, grants, SECURITY DEFINER behavior, rollback, or actual RPC concurrency. This matrix defines the minimum real-database checks before the rate-limit, wallet, analytics, or future Mini Cinema RPC migrations are considered deployable.

## Hard environment boundary

- Use a newly provisioned disposable PostgreSQL/Supabase-compatible database only.
- Never use a production URL, production service-role key, or a database containing real user content.
- Fail before connecting if the configured host matches the known production Supabase project host.
- Do not print connection strings, JWTs, keys, user content, prompts, project payloads, or Storage object names.
- Apply only a reviewed, uniquely ordered test bootstrap. The two historical `0005` files must be reconciled in the disposable bootstrap; do not silently rename production history.
- Record PostgreSQL version and checksums of the exact SQL files tested.

## RPC inventory and required tests

### `consume_message_rate_limit(uuid, integer, integer)` — migration 0011

Privilege contract:
- `SECURITY DEFINER`.
- EXECUTE denied to PUBLIC, anon, authenticated; granted to service_role.
- Table has RLS enabled and no client-role table privileges.
- Backend must derive `p_user_id` from the verified authenticated principal.

Tests:
1. First request for a user in a fresh window returns true.
2. Requests up to the configured limit return true; the next request in the same window returns false.
3. Two independent database sessions racing at the limit cannot both exceed the configured count.
4. A new fixed window resets the count exactly once under concurrent calls.
5. Null user, null/zero/negative/out-of-range limit, and null/zero/negative/out-of-range window values fail closed with a documented SQL error or false result; they must not bypass the limiter.
6. Anonymous/authenticated roles cannot execute the RPC or read/write the counter table.
7. Service role can execute the RPC but cannot obtain a broader client-facing path to the counter table.

### `consume_ai_rate_limit(uuid, text, integer, integer)` — migration 0012

Privilege contract mirrors 0011. The counter key is user + endpoint.

Tests:
1. `chat` and `prompts` have independent counters.
2. Limit enforcement is exact for each endpoint.
3. Concurrent sessions for the same user and endpoint cannot exceed the limit.
4. Concurrent requests across different endpoints do not corrupt or share counters.
5. Invalid/null endpoint, user, limit, and window values fail closed.
6. PUBLIC, anon, and authenticated cannot execute or access the backing table; service_role can execute.

### Wallet lifecycle RPCs — migration 0013

RPCs:
- `grant_user_credits(uuid, bigint, text, text)`
- `reserve_user_credits(uuid, text, text, integer, bigint)`
- `settle_user_credit_reservation(uuid, uuid, bigint)`
- `release_user_credit_reservation(uuid, uuid)`
- `mark_credit_reservation_reconciliation_required(uuid, uuid)`

Privilege contract:
- EXECUTE denied to PUBLIC, anon, authenticated; granted only to service_role.
- Client roles have no table access; service_role has only the explicitly granted SELECT access to wallet, reservation, and ledger tables.
- The trusted backend must derive the target UUID from verified authentication for user-scoped operations. Never forward a browser-supplied `p_user_id` as authority.
- The append-only ledger must not be directly updateable/deletable/truncatable by service_role.

Tests:
1. Grant idempotency: same source/reference/amount replays without a second credit; same key with a different amount conflicts.
2. Concurrent duplicate grants create exactly one ledger grant and one balance increase.
3. Reservation cannot exceed available balance; balance never becomes negative.
4. Concurrent reservations for one wallet serialize; aggregate reserved credits never exceed available funds.
5. Same idempotency key and same reservation parameters returns the same reservation; key reuse with different parameters conflicts.
6. Settlement is idempotent for the same capture amount; different capture amount on replay conflicts.
7. Capture cannot exceed reserved credits; zero capture refunds the reservation according to the documented contract.
8. Release is idempotent for already released rows and cannot release a settled row.
9. Marking reconciliation-required preserves reserved balance and is idempotent.
10. **Ambiguous provider outcome gate:** a reservation in `reconciliation_required` must not be released solely because a client timed out. Current migration source permits release from both `reserved` and `reconciliation_required`; test this explicitly and require a deliberate policy decision before production use. Provider reconciliation must establish the outcome before capture/release.
11. All lifecycle operations use a consistent wallet-before-reservation lock order; concurrent settle/release/mark calls must not deadlock or double-apply ledger deltas.
12. Check balance invariants after every operation: available and reserved balances are nonnegative; wallet balances reconcile to ledger deltas for the fixture user.
13. PUBLIC, anon, and authenticated cannot execute RPCs or read/write wallet tables. Verify function owner and effective EXECUTE ACLs, not just migration text.

### `admin_analytics_summary(timestamptz, timestamptz)` — migration 0014

Privilege contract:
- SECURITY DEFINER with empty search_path and schema-qualified relation references.
- EXECUTE denied to PUBLIC, anon, authenticated; granted only to service_role.
- Backend route separately enforces admin authorization.

Tests:
1. Valid timezone-aware range returns aggregate-only keys and numeric counts.
2. Null, reversed, >31-day, or excessively future range is rejected.
3. The function returns no user identifiers, emails, project payloads, prompts, or message contents.
4. Execute is denied to PUBLIC, anon, authenticated.
5. Verify the function owner can read exactly the required source tables and that effective grants/RLS behavior match the intended trusted boundary.
6. Backend non-admin requests are rejected before RPC invocation; do not treat service_role function grants as a replacement for API admin authorization.

### Future Mini Cinema CAS RPC

Use `docs/MINICINEMA_SERVER_SIDE_CAS_DESIGN.md` as the contract.

Tests:
1. Two sessions save the same expected revision: exactly one succeeds; the other receives a conflict.
2. Save racing with delete cannot revive the deleted row.
3. A stale device cannot restore a tombstone.
4. Restore requires explicit operation and exact tombstone revision.
5. Duplicate idempotency key + identical payload replays the same result; key reuse with a different payload conflicts.
6. User A cannot read or mutate User B's project, even with a guessed UUID.
7. Non-movie project types are rejected by every mutation.
8. Once the cutover is complete, authenticated direct INSERT/UPDATE/DELETE on the table are denied; older clients cannot bypass CAS.

## Current source-level concerns to keep visible

1. Migrations 0011, 0012, and 0013 use `search_path = public, pg_temp` in SECURITY DEFINER functions. This is a hardening item. Validate owners, fully qualified references, effective grants, and function behavior in a disposable environment before changing it. Do not treat this source observation alone as proof of exploitability.
2. Wallet RPCs accept `p_user_id`; the server must derive it from a verified principal and must never trust the browser request body.
3. `release_user_credit_reservation` accepts `reconciliation_required`. This is unsafe if called before an ambiguous provider result is reconciled; do not wire automatic timeout cleanup to this transition.
4. Rate-limit functions use fixed windows. Boundary bursts across adjacent windows are possible by design; decide whether this is acceptable before public launch.
5. The two `0005` migration files prevent assuming a clean CLI order. See `docs/SUPABASE_MIGRATION_RECONCILIATION_RUNBOOK.md`.

## CI acceptance criteria

A future database integration job is acceptable only when it:
- starts an isolated PostgreSQL/Supabase-compatible service from a pinned version;
- bootstraps only the reconciled disposable schema;
- uses separate least-privilege roles for anonymous, authenticated, and service execution tests;
- runs actual concurrent sessions for race tests;
- verifies grants, RLS, function owners, and function settings from system catalogs;
- cleans up automatically and fails closed on production-like connection targets;
- never emits secrets or user content to logs.

Until such a job exists and reports success for the exact PR head, label database behavior **not tested**, not passed.
