# Mini Cinema cloud-sync race audit

Status: initial frontend remediation is implemented on PR #4 and has focused Node regression tests. Latest CI for the current head is not yet available/confirmed. No user data, Supabase schema, Storage policy, or production deployment was changed.

## Scope

Reviewed the current branch's `app.js` account-context handling and Mini Cinema cloud project synchronization, plus the existing cloud-project migration and two-account isolation test plan.

Relevant source areas (line numbers refer to the audited branch snapshot):
- `app.js`: `refreshAuthUI` (~34–69) increments `authContextVersion` when the active user ID changes.
- `app.js`: `movieStorageKey` (~928) and `movieDeletedKey` (~940) partition browser project data and deletion tombstones by current account ID.
- `app.js`: `movieToCloudRow` (~949) reads `authSession.user.id` from mutable global state while building a cloud row.
- `app.js`: `scheduleMovieCloudSync` (~978–1018) schedules delayed work and uses global `authSession` inside the callback.
- `app.js`: `loadMovieProjectsFromCloud` (~1019–1063) captures a user ID and checks it after the initial read, but does not capture/check the auth context generation.

## Findings

### F-01 — Delayed sync does not bind itself to the initiating account (confirmed)

The 350 ms timer callback checks only that some user is currently signed in. It does not capture the initiating `userId` or `authContextVersion`. After an account switch, a callback scheduled under account A can continue running under account B's mutable global session.

Impact: the callback may read B's current local project/tombstone keys and construct requests using whichever session is current when the callback runs. This is not proof of an observed cross-account leak, but it makes ownership and operation intent ambiguous and is unsafe for a security-sensitive sync path.

### F-02 — Cloud row serialization reads mutable global identity (confirmed)

`movieToCloudRow(project)` assigns `owner_id: authSession.user.id`. The serializer does not accept an explicit owner ID. Its output therefore depends on global session state at serialization time rather than the account that initiated the operation.

Impact: row ownership cannot be reasoned about locally from the project snapshot and operation context. Server RLS remains an important boundary, but client-side account binding should be explicit as defense in depth.

### F-03 — One global sync queue is shared across accounts (confirmed)

`movieCloudState` contains one `syncing`, `pending`, and `timer` state for the whole browser. A pending operation from A and a new write from B share the same queue flags. The queue does not carry an account ID or generation.

Impact: account A and B work can coalesce into a single follow-up run. This can cause confusing retries/status messages and makes race behavior difficult to test or reason about.

### F-04 — Account context is not revalidated after every asynchronous boundary (confirmed)

The cloud sync callback awaits deletion and upsert operations, but it does not compare a captured account ID plus `authContextVersion` after each await before touching tombstones, local storage, UI feedback, or retry state.

The cloud-load path checks the user ID after the first SELECT, which is useful, but should also bind the operation to the captured context generation and revalidate before all subsequent state changes. A same-user sign-out/sign-in or a later session generation should not allow stale responses to mutate the new session's state.

### F-05 — Existing local account partitioning is a positive safeguard (confirmed)

`movieStorageKey()` and `movieDeletedKey()` include the active user ID (or `guest`). This reduces accidental local mixing when reads and writes occur under the correct active context. Preserve these keys and existing local drafts during remediation; do not rename or clear them as part of the first fix.

## Required remediation design

1. Capture an immutable operation context at scheduling time: `ownerId`, `authContextVersion`, and a unique operation generation.
2. When the timer fires, abort unless the current session still has the captured owner ID and context version.
3. Pass `ownerId` explicitly into row serialization: `movieToCloudRow(project, ownerId)`. Never read global `authSession` inside the serializer.
4. Build tombstone keys and local-storage keys from the captured owner ID, not from the mutable current session.
5. Before and after every awaited Supabase operation, revalidate both owner ID and context version. If either differs, stop without updating local state, UI, tombstones, or retry flags for the new account.
6. Replace the global boolean queue with an account-keyed queue or invalidate/cancel the previous account's timer and pending generation on every account-context change.
7. Ensure cleanup in `finally` only clears state belonging to the same operation generation; an old A operation must not clear B's queue flags.
8. Keep server-side RLS and ownership constraints as the primary security boundary. Client guards are defense in depth, not a substitute.
9. Preserve current guest behavior: guest drafts remain local, and no implicit guest-to-account import is introduced.

## Deterministic regression tests required before changing production frontend code

Use a mocked Supabase client with deferred promises and fake timers.

- A schedules sync; before 350 ms, switch to B; advance timers. Assert A's scheduled callback performs no B-scoped read/write and does not update B's UI.
- A sync starts and pauses at deletion; switch to B; resolve A deletion. Assert no A continuation reads B's local keys or mutates B tombstones/UI.
- A sync starts and pauses before upsert; switch to B; resolve the first request. Assert no A project row is serialized or submitted with B's owner ID.
- A starts a cloud load; switch to B before SELECT resolves. Assert A's response is not merged into B local state.
- A signs out and signs back in as A while a prior load is pending. Assert the stale generation cannot overwrite the new generation's local state.
- A sync is pending; B schedules sync. Assert queue cleanup from A cannot clear B's pending operation.
- Guest creates a local draft, then signs in as A. Assert the guest draft is not uploaded or assigned to A without an explicit import action.
- Verify the Supabase query still relies on authenticated RLS and owner filters; a client-side owner value alone must never grant access.

## Implementation gate

The current repository has no demonstrated browser-level test harness for these account-switch scenarios. Do not patch the live Mini Cinema synchronization logic until a deterministic test harness is added and the above tests pass. The backend asset-owner helper does not fix this frontend race.

No live Supabase query, SQL migration, RLS change, Storage operation, or production deployment was performed for this audit.

## Remediation progress (2026-11-24)

Implemented on the PR branch (not merged to `main`):

- Added `movie-cloud-context.js` with immutable `{ ownerId, authContextVersion }` capture and current-context checks.
- Loaded the guard before `app.js` in `index.html`.
- Changed `movieToCloudRow(project, ownerId)` to serialize the captured owner explicitly.
- Added context checks before and after awaited sync/load operations, before local merge/UI feedback, and before tombstone updates.
- Bound deletion filters to the captured `context.ownerId`.
- Replaced global boolean sync flags with `syncingContext` and a latest-only `pendingContext`; stale pending work is discarded rather than replayed under another account.
- Bound cloud-load cleanup to the exact captured context object, so an older A load cannot clear the loading marker for a newer A login generation.
- Added Node built-in test coverage for immutable context capture, A→B invalidation, same-user new generation, latest pending-context selection, and stale pending-context rejection.

Current focused test file: `tests-frontend/movie-cloud-context.test.js`.
CI workflow: `.github/workflows/frontend-context-tests.yml`.

Important limitation: these are unit tests for the context guard and pending-context state helpers, not a full browser integration harness with mocked Supabase deferred promises/fake timers. The broader end-to-end scenarios listed above remain required before treating the account-switch race as fully closed. The PR head is still draft/open and unmerged; no production deployment has occurred.
