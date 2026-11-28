# Async account-context fencing

## Purpose

Prevent work started in one authenticated account (or guest session) from mutating another session's UI or local state after an account boundary change.

## Shared account context

The frontend increments `authContextVersion` whenever the authenticated user identity changes. Async operations should capture both:

- the context version at operation start;
- the originating user ID (or `null` for guest).

Before applying an async result, writing account-scoped local state, or updating shared UI, verify that both values still match the current context.

## Covered flows

- Character Library render/save/delete and IndexedDB image ownership checks.
- AI Companion message/history operations, including stale submit cleanup and focus management.
- Community profile save cleanup.
- Profile avatar save cleanup and picker-button state.
- Cloud movie loading and tombstone cleanup before local writes.
- Audio → Story generation and handoff to Mini Cinema. A generated result is bound to the account context that requested it; the handoff rejects results from a prior session.
- Audio Lab discards stale generation results, clears the previous result on account change, and only unlocks the generate button for the request that still owns the UI.

## Required pattern

1. Capture `authContextVersion` and the current user ID before the first await.
2. Define a local `contextIsCurrent` predicate.
3. Recheck after every await that precedes an account-scoped side effect.
4. Recheck before localStorage/IndexedDB writes, rendering, status changes, or shared button cleanup.
5. A stale request must not unlock, focus, clear, or overwrite controls now owned by another account.
6. Keep owner checks in the backend and storage layer; frontend fencing is defense in depth, not an authorization boundary.

## Verification

The feature-branch workflow runs JavaScript syntax checks and Python contract tests for the account-fencing invariants. Browser IndexedDB, backend unit, and disposable PostgreSQL integration tests run in separate CI jobs.

These checks do not imply production deployment or live Supabase verification. Feature migrations remain unapplied to production, and the application remains unchanged on the live deployment until an explicitly approved release.
