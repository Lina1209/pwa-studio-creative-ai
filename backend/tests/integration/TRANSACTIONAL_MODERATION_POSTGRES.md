# Transactional moderation PostgreSQL integration test plan

These are rollout-gating tests, not unit-test substitutes. They must run against an isolated disposable PostgreSQL database with the exact proposed moderation schema and role grants. Never point this suite at production Supabase.

## Environment contract

The test harness must provision:
- PostgreSQL with `auth.users` and the exact `user_reports`, `user_suspensions`, and `admin_audit_log` definitions used by the candidate migration;
- distinct fixture users for reporter, reported account, moderator A, and moderator B;
- a non-owner application role and a service role matching the intended Supabase execution grants;
- the candidate transactional RPC SQL from `supabase/proposals/`.

The harness must fail fast if the database URL points to a known production Supabase host. Do not store credentials in repository files or CI logs. Use ephemeral CI secrets only if/when a dedicated test database is provisioned.

## Required test cases

### Atomic rollback
For each of report review, suspension create, and suspension revoke:
1. Begin from a known committed fixture state.
2. Force the audit insert to fail using a test-only trigger or constraint in the disposable database.
3. Call the RPC.
4. Assert the RPC fails.
5. Assert the moderation row is byte-for-byte unchanged from its pre-call state.
6. Assert no idempotency row was committed.
7. Assert no audit event was committed.

The failure injection must affect only the disposable test database and must be removed after the test.

### Report concurrency
- Create one pending report.
- Run two concurrent review calls with different moderator IDs and the same expected status but different outcomes.
- Assert exactly one succeeds.
- Assert the other receives the documented stale-state conflict.
- Assert one final report transition and exactly one corresponding audit event.

### Idempotent suspension creation
- Submit two concurrent requests with the same idempotency key and identical normalized payload.
- Assert both calls resolve to the same suspension ID.
- Assert exactly one suspension and one audit event exist.
- Reuse the key with a different actor, operation, or payload; assert conflict and no additional mutation.

### Idempotent revocation
- Submit the same revoke key concurrently.
- Assert both calls resolve to the same result and only one audit event exists.
- Submit a new key after the suspension is already revoked; assert the documented already-revoked conflict and no second event.

### Privilege boundary
- Verify execute permission is granted to `service_role` only.
- Verify `PUBLIC`, `anon`, and `authenticated` cannot execute the RPCs.
- Verify direct authenticated-client writes to suspension and audit tables remain denied.
- Verify service-role audit access remains append-only according to the final grant model.

## Harness quality requirements

- Use actual concurrent database sessions, not sequential mocks.
- Use explicit transaction isolation and bounded timeouts so deadlocks fail the test rather than hanging CI.
- Assert both row counts and complete relevant row values.
- Never print connection strings, API keys, JWTs, report descriptions, or user content.
- Reset fixtures between tests and ensure no test data persists after the suite.
- Record PostgreSQL version and migration checksum in test output.

## Not yet runnable

The repository currently has no confirmed isolated PostgreSQL test database or integration harness. The candidate RPC SQL has not yet been authored because the live migration ledger, actual schema, grants, and duplicate migration history have not been reconciled. These tests must not be represented as passing until the disposable database and candidate SQL exist and the full suite has run.
