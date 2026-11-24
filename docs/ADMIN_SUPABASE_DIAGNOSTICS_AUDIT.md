# Backend Supabase diagnostics audit

Date: 2026-11-24  
Scope: source review of the admin diagnostics route and its service/tests on the isolated PR branch. No live Supabase request was made.

## What the endpoint actually verifies

`GET /api/admin/diagnostics/supabase` is protected by `require_admin`. The route invokes a server-side diagnostics helper and does not return the configured API key. The helper performs:
- one REST root reachability request;
- read-only PostgREST `HEAD` requests with `limit=0` for selected tables;
- metadata-only status labels: available, missing/not exposed, not accessible, unreachable, or not checked.

It does not select table rows. A successful HEAD means the configured server credential can resolve the requested table/column through PostgREST. It does **not** prove RLS correctness for user JWTs, column completeness, constraints, triggers, function privileges, migration history, Storage policies, or account isolation.

## Changes made

Expanded `backend/app/services/diagnostics_service.py` table probes to cover:
- community profiles and Mini Cinema projects;
- notifications, direct conversations/messages, user blocks;
- reports, suspensions, moderation audit;
- AI Companion conversations/messages and AI usage;
- AI rate limits;
- wallet, reservations and ledger;
- legacy profiles, projects, characters, scenes and media.

The diagnostic uses bounded parallel HEAD checks (six workers, three-second request timeout) to keep the expanded read-only inventory responsive. Results remain metadata-only. Wallet table presence is not evidence that wallet billing is enabled.

Updated `backend/tests/test_diagnostics.py` to cover the expanded table map, read-only HEAD behavior, inaccessible/missing/unreachable states, missing configuration, and secret non-disclosure.

## Security observations

1. The route is correctly admin-gated in source; tests assert unauthenticated callers receive 401 and creators receive 403 before inspection runs.
2. The service credential remains server-side and the result contains only a coarse key-kind label, never the key itself.
3. The current `available` state is intentionally narrow. It must not be presented in the admin UI as “table secure” or “migration applied”.
4. The diagnostic does not inspect Storage buckets or policies, Postgres RLS/grants, function ACLs, trigger definitions, or migration-ledger records. Those remain the responsibility of the read-only SQL inventory and a later reviewed live audit.
5. PostgREST may report missing or not exposed for a table because of schema exposure/configuration as well as absence. The label deliberately preserves that ambiguity.

## Follow-up requirements

- Add explicit UI copy explaining that this is a connectivity/table-availability check, not a full security certification.
- Add a separate admin-only live database inventory only if a safe, bounded server-side mechanism is designed; do not attempt to run arbitrary SQL through the REST API.
- Verify actual RLS and cross-account behavior with two controlled accounts in a disposable project before enabling public community/storage workflows.
- Keep all migrations unapplied until the duplicate 0005 migration history and live state are reconciled.

## Safety boundary

No live database was queried, no user rows were read, no secrets or environment variables were changed, no SQL was applied, and no production deployment or PR merge was performed.
