# AI Companion Conversation History Isolation Audit

Date: 2026-11-24
Scope: source-only review of AI Companion history, authentication context handling, persistence schema/RLS, and the chat request path. No live Supabase queries, SQL execution, production changes, or deployment were performed.

## Reviewed
- `app.js` (AI Companion history, auth context reset, dashboard activity)
- `backend/app/main.py` (authenticated `/api/chat` route)
- `backend/app/schemas.py` (`ChatRequest`)
- `backend/app/services/auth.py` (verified Supabase JWT identity)
- `backend/app/services/ai_service.py` (provider request and diagnostic logging)
- `backend/app/services/usage_service.py` (metadata-only usage telemetry)
- `supabase/migrations/0004_assistant_chat_history.sql`
- Existing backend and frontend test inventory

## Positive controls observed

1. `/api/chat` requires `get_current_user`; the caller identity is derived from a verified Supabase JWT, not a request-body user ID.
2. The chat payload accepts only a bounded message string (1–12,000 characters); no client-supplied provider, model, API key, owner ID, or price is accepted.
3. The chat route checks suspension, content safety, and an account-scoped AI rate limit before provider invocation.
4. Provider credentials are selected server-side. Provider errors are logged as metadata (provider/model/error type/status code), not raw prompts or credentials.
5. AI usage telemetry stores request/user/endpoint/provider/model/token/cost metadata and explicitly does not store prompt or response text.
6. Conversation rows are queried with `user_id = authenticated user`; message reads additionally filter by both conversation ID and user ID.
7. The migration enables RLS on both history tables. Conversation policies require `auth.uid() = user_id`; message policies require the same and verify that the parent conversation belongs to `auth.uid()`.
8. The message table has a foreign key to the conversation with cascade delete. User ID is non-null and references `auth.users`.
9. On an account identity change, `refreshAuthUI` clears the selected conversation, history list, and visible messages. Async history/message reads capture user ID and auth-context version and suppress stale results.
10. Message inserts touch the parent conversation's `updated_at`, allowing recent conversations to be ordered.

## Findings and recommendations

### AIC-1 — High: authenticated clients can forge assistant-role history rows
The migration grants authenticated users SELECT, INSERT, UPDATE, and DELETE on both history tables. The RLS policy correctly limits each row and its parent conversation to the signed-in owner, but it does not restrict which role a client may insert or update. The CHECK constraint permits both `user` and `assistant`. Therefore, a signed-in user can directly create or modify an `assistant` message without a corresponding backend AI response. This does not provide cross-account access, but it weakens history integrity and makes the transcript unsuitable as a trusted record of actual AI output.

Recommendation: move message persistence behind narrowly scoped backend endpoints/RPCs. Permit clients to create only user messages; allow assistant-role writes only through a server-controlled path. If direct client access remains, add database enforcement that prevents authenticated clients from inserting/updating assistant-role rows. Keep service credentials server-side.

### AIC-2 — Medium: conversation title updates do not refresh ordering timestamp
The trigger updates the conversation timestamp after message INSERT only. The UI renames a conversation by directly updating `title`, but that update does not refresh `updated_at`. A renamed conversation may therefore remain in its old position in recent-history ordering.

Recommendation: add a conversation BEFORE UPDATE trigger for `updated_at` (or update timestamp explicitly in a trusted service) and test rename ordering.

### AIC-3 — Medium: history list has no pagination or explicit retention boundary
The primary history view selects every conversation for the account without a limit/cursor. Dashboard activity is limited to five, but the main history list can grow indefinitely and become slow for active users.

Recommendation: implement cursor pagination ordered by `updated_at DESC, id DESC`, a bounded page size, and a deliberate retention/export policy. Do not silently delete user creations or conversation history.

### AIC-4 — Medium: global history-loading lock can drop a refresh during account switching
`assistantHistoryBusy` is a single global boolean. If account A's history request is in flight when the auth context switches to account B, B's scheduled history refresh can return early because the flag is still set. A's stale response is correctly suppressed and the lock is eventually released, but there is no guaranteed retry for B. The visible list is cleared on account switch, so this is primarily a reliability issue rather than a demonstrated cross-account disclosure.

Recommendation: key the in-flight state by auth-context generation/user, or queue one pending refresh and run it after the old request finishes. Add a deterministic deferred-promise test for A→B during history loading.

### AIC-5 — Medium: async history mutations need auth-generation guards
Opening a conversation is guarded after the SELECT. However, rename and new-conversation creation do not capture and revalidate the initiating user/context after each awaited operation. RLS still prevents one account from mutating another account's rows, but a late completion can update status/render state for the newly active account or leave an orphaned empty conversation in the initiating account.

Recommendation: capture `user_id` and `authContextVersion` at the start of every history action; use the captured ID in every query; after each await, abort UI updates unless the context still matches. Add A→B race tests for create and rename.

### AIC-6 — Low: dashboard and main history duplicate conversation queries
The dashboard separately fetches recent conversations while the main history component also loads the full list. This is not an isolation defect, but it duplicates requests and can show inconsistent snapshots.

Recommendation: share a small account-scoped repository/cache with generation-aware invalidation, while never persisting message bodies in shared/local cross-account storage.

### AIC-7 — High (live-state verification required): migration state and effective privileges are unknown
The repository migration describes RLS and table grants, but source inspection cannot prove that migration 0004 has been applied to the connected Supabase project, that no additional permissive policies exist, or that effective table/function privileges match the file. The trigger function's effective owner/security behavior also needs confirmation in the live catalog.

Recommendation: before enabling or relying on cloud history in production, perform a read-only live audit of migration history, table definitions, constraints, indexes, all policies, grants, trigger/function definitions, and anon/authenticated/service_role privileges. Then run disposable two-account isolation tests. Do not apply or alter SQL until the live state is reconciled.

## Important product/privacy note
AI Companion conversations may contain personal creative ideas or sensitive text. Keep history private by default, avoid prompt/response content in telemetry and logs, provide a clear user-controlled delete/export policy, and never expose message bodies in public creator profiles or the PУЛЬС gallery.

## Recommended implementation order
1. Resolve AIC-1 so assistant output cannot be forged through the public client.
2. Add auth-generation guards and deterministic A→B tests for create/rename/load.
3. Fix timestamp semantics and add bounded pagination.
4. Reconcile live Supabase migration/RLS/grants read-only before any schema changes.
5. Add integration tests with two disposable accounts and verify no cross-account read/write/delete.

## Explicitly not performed
- No Supabase SQL, migration, RLS, grant, bucket, or policy was applied or changed.
- No live user conversations were read or modified.
- No production environment variables, provider keys, or billing settings were accessed or changed.
- No PR merge or production deployment was performed.
