# AI Companion and Project Recovery — Follow-up Audit

Date: 2026-11-25
Scope: read-only source inspection of the PR branch. No live Supabase reads, SQL execution, project edits, account switching in production, or deployment were performed.

## AI Companion history

### Confirmed working in source
- Conversation and message records are stored in Supabase tables `assistant_conversations` and `assistant_messages`.
- The UI filters conversation lists by the authenticated user's UUID and message reads by both conversation ID and user UUID.
- The migration enables RLS and ties message access to a parent conversation owned by the same authenticated user.
- On account identity change, the visible history and messages are cleared; message loading captures user ID and auth-context version and discards stale results.
- The chat request uses the authenticated backend `/api/chat`; prompt text is not part of the usage telemetry schema.
- New conversations and messages are saved directly by the browser Supabase client.

### Remaining risks
1. **History integrity (high):** migration 0004 grants authenticated users INSERT and UPDATE on assistant messages, while the role constraint permits both `user` and `assistant`. A user can therefore forge assistant-role history rows through direct client writes. RLS protects ownership, not the truth of the assistant role. Move assistant-role persistence behind a trusted server path or enforce role-specific database permissions before treating transcripts as authoritative.
2. **Account-switch refresh race (medium):** `assistantHistoryBusy` is one global boolean. If account A is loading history during a switch to B, B's refresh may return early and is not guaranteed to be retried after A finishes. Stale A results are suppressed, so this is a reliability issue rather than evidence of cross-account disclosure.
3. **Create/rename context races (medium):** conversation creation and rename do not consistently capture and revalidate the initiating user/context after every awaited operation. RLS remains a boundary, but stale completions can alter active UI state or produce confusing failures after an account switch.
4. **Unbounded history (medium):** the conversation list has no cursor pagination or explicit retention/export policy.
5. **Rename ordering (medium):** migration trigger updates conversation `updated_at` on message insert, but title-only updates do not refresh ordering timestamp.
6. **Live-state gate:** migration 0004, effective grants/policies and trigger behavior have not been inspected in the live Supabase project. Source migrations do not prove deployed state.

## Mini Cinema project recovery

### Confirmed working in source
- Signed-in local projects are partitioned by account UUID; guest projects use a separate `guest` namespace.
- Cloud project operations capture owner/auth-generation context and reject stale operations. Cloud reads/writes/deletes are owner-scoped and restricted to `project_type = movie`.
- Local drafts are preserved on logout; account switching resets the active editor rather than transferring one account's projects to another.
- Project version snapshots are deep copies, newest-first, capped at 20, and restore preserves the current state as a new snapshot before applying the selected version.
- Guest drafts receive a 24-hour expiry and can be exported as a `.pwa-project.json` file.
- Local storage read failures block writes/sync rather than silently replacing the project list with an empty array.

### Remaining risks
1. Cloud project deletion tombstones are held in browser localStorage until cloud sync succeeds. Clearing browser storage or losing the device before sync can lose a pending delete and allow the cloud row to reappear.
2. Project version history is stored inside the project JSON payload; it is not a separate server-side immutable revision log.
3. Conflict protection uses client timestamps and local re-reads. It is not transactional multi-device collaboration and remains exposed to clock skew, simultaneous cloud writes and timestamp collisions.
4. Browser localStorage is not encrypted by this application. Account namespacing prevents ordinary UI mixing but does not protect data from someone with access to the same browser profile/device.
5. Guest expiry/export and account switching are source-reviewed; they have not been exercised against the live app in this audit.

## Release and test status
- GitHub Actions for commit `9fd81997f660b645a39a84011810a9d824eef74b`: `test`, `movie-cloud-context`, and `rate-limit-rpc` all completed successfully.
- These checks do not validate the live Supabase migration ledger, RLS/grants, two-account behavior or cross-device recovery.
- PR #4 remains open and draft. No merge or production deployment was performed.

## Recommended next sequence
1. Fix AI Companion auth-generation races and add deterministic A-to-B deferred-promise tests.
2. Design a trusted persistence path for assistant-role messages; do not simply revoke privileges without a compatible server write path.
3. Add bounded conversation pagination and update-timestamp semantics.
4. Run read-only live Supabase diagnostics, then disposable two-account tests.
5. Test project save/reload, restore, account switch, guest expiry/export, offline deletion and cross-device recovery with disposable test accounts.
6. Only after those gates, move on to shared character/voice/audio/video asset architecture and implementation.

## Explicit non-actions
No live Supabase query or mutation, SQL migration, user-data access, upload/download, billing action, merge, or deployment was performed.
