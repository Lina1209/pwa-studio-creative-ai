# Community Profile Privacy and Account Isolation Audit

Date: 2026-11-24  
Audited revision: `53d074d66d7a5a654b11f196a9b7fde7dedd8551`  
Scope: backend source and migration review only. No live database or profile records were accessed.

## Controls verified

- Profile endpoints require a verified `StudioUser`; the account UUID is taken from the verified token, not from caller-supplied profile data.
- Profile update schema exposes only username, display name, bio, visibility, and directory visibility. It does not allow changing `user_id` or `avatar_path`.
- The profile service validates UUIDs and applies additional username/display-name/bio validation.
- Own-profile read and update REST calls filter by the authenticated user's UUID.
- Public directory search selects only explicitly public fields and filters to `visibility=public` and `show_in_directory=true`; it excludes the current user's own row.
- Public profile lookup returns a generic 404 when the profile is private, hidden from the directory, or absent.
- Public profile serialization omits private visibility flags and any auth email/metadata.
- Migration `0009_user_profiles.sql` enables RLS, revokes direct client writes, grants only SELECT to authenticated users, and limits direct reads to public directory profiles or the account's own profile.
- The profile table stores no email, password, auth metadata, or other account credentials.

## Follow-up items

### P1 — Profile-service regression coverage is now present; live A/B verification remains

A focused `backend/tests/test_profile_service.py` module now covers allowlisted public serialization, public-directory filters, non-enumerating 404 behavior, rejected search input, UUID validation, invalid update rejection, and owner-scoped updates. These are mocked service tests; they do not replace PostgreSQL/Supabase integration tests.

**Remaining integration tests:**
- User A cannot read or update User B's own profile through live two-account requests.
- Private or directory-hidden profiles return the same non-enumerating 404.
- Public search never returns private/hidden rows or the current user.
- Profile update cannot alter `user_id`, `avatar_path`, email, or arbitrary columns.
- Username normalization, uniqueness conflicts, and invalid Unicode/control characters are handled consistently.
- Concurrent first-time profile initialization is safe and idempotent.

### P2 — Public directory flag and profile visibility are separate controls

The current service requires both `visibility=public` and `show_in_directory=true` for search and public profile lookup. This is privacy-preserving. Product UI should explain the distinction clearly so users understand that disabling directory listing also hides direct public profile access.

### P3 — First-login profile initialization should be race-safe

`get_own_profile` performs a SELECT followed by INSERT. Concurrent first requests for the same account may race on the primary key. The generated username is deterministic, so the normal result is a duplicate-key error rather than cross-account exposure, but the API may return a transient failure.

**Recommended correction:** use an idempotent database upsert/RPC with conflict handling, then read back only the same authenticated user's row.

## Rollout gates

1. Reconcile live schema, RLS, and grants for `user_profiles` with the migration ledger before changing SQL.
2. Add the profile-service tests above and a two-account A/B integration test.
3. Confirm public/private/directory controls are accurately explained in the UI.
4. Do not add public creator pages, followers, or public media links until profile and media visibility policies are verified together.

## Explicit non-actions

- No live profile data was read or changed.
- No SQL or migration was executed.
- No profile was made public or private.
- No deployment or PR merge was performed.


## Audit refresh — 2026-11-24

The focused profile-service test module is present in the current PR branch. Its mocked tests verify the service's owner filters and public-field allowlist. The original P1 item is therefore partially resolved at source/test level; live two-account and database integration checks remain outstanding.

The first-login SELECT-then-INSERT race remains open. No production database change is recommended until the live schema and migration ledger are reconciled.
