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


## Repository harness inventory (checked 2026-11-25)

The branch was inspected before deciding whether a database job can be added safely:

- `.github/workflows/backend-tests.yml` installs Python 3.12 and runs `pytest -q` from `backend/`; it does not start PostgreSQL or Supabase.
- `backend/requirements.txt` contains the application HTTP/AI dependencies; it does not declare a PostgreSQL driver or database test framework.
- `backend/tests/integration/` currently contains the transactional-moderation PostgreSQL test-plan document, not an executable database harness.
- Repository searches found no `docker-compose`/Compose setup, `supabase/config.toml`, psycopg dependency, or pgTAP harness. The `supabase/` tree contains migration and diagnostic SQL directories.
- The root does not expose a `package.json` at this branch path; frontend tests are separate Node scripts under `tests-frontend/` and do not supply a PostgreSQL runtime.

**Decision:** do not add a workflow that blindly replays every migration. The duplicate `0005` versions, Supabase Auth/Storage dependencies, and unresolved live migration history mean the disposable bootstrap must first be deliberately assembled and validated. The RPC matrix remains a specification; no database service was provisioned and no SQL was executed during this inventory.


## First executable PostgreSQL gate — 2026-11-25

A narrow disposable integration harness is now present for migrations 0011 and 0012 only:

- `backend/tests/integration/test_rate_limit_rpc_postgres.py` applies the exact two rate-limit migration files to a fresh PostgreSQL fixture with minimal Supabase Auth/role scaffolding.
- `.github/workflows/disposable-postgres-rpc-tests.yml` provisions an ephemeral PostgreSQL 16.4 service for the test job. The test code refuses non-local database hosts and tears down its fixture schema after the run.
- It checks exact limit behavior, per-endpoint AI counters, concurrent sessions at the limit, fixed-window reset, invalid message-limit input, and role/function/table privilege boundaries.
- The workflow passed on branch HEAD `7f6dcaf7aae48e71cfa4ec45e7efe4c0bdf96e87`: [Disposable PostgreSQL RPC tests run #3](https://github.com/Lina1209/pwa-studio-creative-ai/actions/runs/45472616619).
- The same HEAD also passed backend tests and frontend account-context tests: [Backend run #438](https://github.com/Lina1209/pwa-studio-creative-ai/actions/runs/45472616122), [Frontend run #437](https://github.com/Lina1209/pwa-studio-creative-ai/actions/runs/45472619640).

**Scope limitation:** this is not a full Supabase emulator and does not test Auth internals, Storage, wallet migration 0013, analytics migration 0014, or production grants/schema. The wallet and analytics RPCs remain untested against PostgreSQL. The minimal `auth.users` table is only a disposable FK target. Do not interpret this result as approval to apply any migration to production.

The initial harness commit exposed two CI integration issues: the backend unit workflow did not install the optional psycopg driver, and a pre-existing frontend source-boundary assertion did not account for the version-count text in the button label. Both were corrected; the latest exact branch HEAD passed all three workflows.


## Unified wallet RPC gate — 2026-11-25

Migration `0013_unified_credit_wallet.sql` is now included in the same disposable PostgreSQL 16.4 fixture after migrations 0011/0012. The CI run completed with **14 passed, 1 xfailed**:

- Grant idempotency: duplicate source/reference does not duplicate credits; changed amount is rejected.
- Concurrent duplicate grants: exactly one grant ledger event is created.
- Concurrent reservations: 16 competing reservations against 100 credits at 10 credits each produce exactly 10 reservations and 6 insufficient-credit responses; the wallet never overdraws.
- Concurrent retry with one reservation idempotency key: one reservation/ledger event, all other calls replay the same reservation.
- Changed reservation parameters under the same key are rejected.
- Partial settlement refunds unused credits; same-amount settlement replay is idempotent; changed capture amount is rejected.
- Full release returns reserved credits once; duplicate release does not append a second release event.
- RPC execution grants and service-role ledger read-only permissions are checked.

**Known failing safety invariant (recorded as expected-failure / xfail):** after `mark_credit_reservation_reconciliation_required`, the current migration still permits `release_user_credit_reservation`. That can return credits while a provider outcome is ambiguous. The test encodes the desired future rule (release must be rejected until an explicit reconciliation decision) and is marked xfail so the present branch stays green while visibly retaining this known gap. Do not blindly release a reservation after a provider timeout. A forward migration with an explicit resolution model is needed; do not rewrite migration 0013 if it may already have been deployed.

Latest tested branch commit at this gate: `34fe534a3136fd420a7b41595ea411c22a744477`. Disposable PostgreSQL workflow: [run](https://github.com/Lina1209/pwa-studio-creative-ai/actions/runs/45473190008). Backend and frontend workflows also passed on the same commit.

This is source-migration testing in an isolated plain PostgreSQL service with minimal `auth.users` and role scaffolding, not a full Supabase emulator or production schema validation. Migration 0014 and live grants/RLS remain outside this test scope.


## Follow-up hardening and analytics gate — 2026-11-25

A forward-only migration, `0015_credit_provider_outcome_resolution.sql`, now addresses the previously recorded ambiguous-provider release gap without rewriting migration 0013:

- Ordinary settle/release RPCs now accept only `reserved` state. They reject `reconciliation_required`.
- New service-role-only `resolve_credit_reservation_provider_outcome` requires an explicit `succeeded` or `failed` outcome and a non-empty provider resolution reference.
- A confirmed success is settled with a bounded capture amount; a confirmed failure releases the reservation. The state transition and balance/ledger mutation occur in one database transaction.
- Replays with the same final outcome/reference return `already_resolved`; conflicting final outcomes are rejected.
- Null outcomes, missing references, invalid capture combinations, and capture amounts above the reservation are rejected.
- This remains a trusted backend boundary: the server must call the resolver only after it has authoritative provider evidence. A caller-supplied reference alone is not proof.

The disposable fixture now applies migrations 0011, 0012, 0013, 0014, and 0015 in version order, with minimal test-only `profiles`, `projects`, and `ai_usage` scaffolding for analytics. The latest tested commit `578ce198b1db54451b8fd4f052d906a432f01ae2` reports **19 passed** in the PostgreSQL suite. It covers:
- Explicit provider failure resolution, rejection of direct release/settle while ambiguous, idempotent resolution, and rejection of conflicting resolution.
- Explicit provider success resolution and correct capture/refund accounting.
- Admin analytics aggregate counts, date-range validation, and service-role-only execution.
- All previously listed rate-limit and wallet concurrency/lifecycle cases.

Latest PostgreSQL run: [run 45473891705](https://github.com/Lina1209/pwa-studio-creative-ai/actions/runs/45473891705). Backend tests: [run 45473891875](https://github.com/Lina1209/pwa-studio-creative-ai/actions/runs/45473891875). Frontend account-context tests: [run 45473891643](https://github.com/Lina1209/pwa-studio-creative-ai/actions/runs/45473891643).

The fixture is still plain disposable PostgreSQL with minimal Supabase role/auth/table scaffolding. It is not a production schema check, full Supabase emulator, or proof that migrations 0013–0015 are applied in the live project. Do not deploy these migrations until the live migration ledger and schema have been reconciled, and ensure the backend has a provider-authoritative reconciliation path before enabling paid generation.
