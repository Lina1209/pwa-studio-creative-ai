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


## Follow-up audit — guest expiry, offline behavior, and shared creative assets (2026-11-25)

### Guest project expiry — source review
- Guest projects are stored under the separate localStorage key `pwa-studio-movie-projects:guest`; signed-in projects use the authenticated UUID namespace.
- New guest projects receive a 24-hour `guestExpiresAt` deadline. Legacy guest records without a valid deadline are normalized to 24 hours from first subsequent read; a valid existing deadline is preserved and is not extended.
- Expired guest records are filtered from the guest list and removed from the guest namespace only. The signed-in read path does not apply guest expiry filtering.
- Guest export is available from the guest-space UI before expiry.
- The expiry helper has focused unit tests for preserving deadlines, normalizing missing/malformed deadlines, and non-mutating behavior.
- Limitation: these are source and unit-test findings, not a timed browser test. Expired drafts are removed from browser storage on read; there is no server-side recovery copy for guests. Users must export before expiry.

### Offline / PWA behavior — source review
- A service worker is registered and caches the application shell. Core shell assets use network-first with cached fallback; other same-origin GET requests use cache-first behavior.
- Supabase REST/Auth traffic is cross-origin and is not covered by the same-origin cache strategy.
- No durable offline write queue, background sync, or explicit online-event replay path for project mutations was found in the reviewed source. The Mini Cinema cloud sync is an authenticated online Supabase operation, not an offline-first sync engine.
- Therefore: the app shell may open offline if previously cached, and local drafts can remain on-device, but cloud save/load, account auth, AI requests, and media upload are not available offline. Do not describe the product as having full offline synchronization.
- Existing cloud sync uses debounced scheduling and account-context checks, with owner-scoped reads/upserts/deletes, tombstones, payload limits, and stale-cloud preflight. It is online synchronization only; timestamp-based conflict checks are not transactional compare-and-swap.

### Shared characters, voices, audio, image and video
- The current source contains Mini Cinema character/voice planning text fields and a partial Audio Studio UI for microphone capture and local audio-file preview.
- The audio UI explicitly reports that selected files and microphone recordings remain on the device; it does not upload them or generate speech/music.
- No connected image, video, music, TTS, voice-cloning, or transcription provider workflow was verified in the source inventory.
- The existing `studio_characters`, `studio_scenes`, and `studio_media` migration tables are a database foundation only; there is no verified reusable asset CRUD/upload/signed-download API or cross-studio asset-link workflow.
- The canonical shared asset registry remains a future architecture task. The intended design is one owner-scoped asset ID referenced by multiple projects/studios, rather than duplicating the same original for each studio. This is a design target, not an implemented feature.

### CI and pull request status
- GitHub Actions for commit `b5cfc292c29e2e9e76abd7b02fab5703e7ad764c` were rechecked: `test`, `movie-cloud-context`, and `rate-limit-rpc` all completed successfully.
- PR #4 remains open and draft, with no merge. Its mergeability is currently reported as false by GitHub; this is not a CI failure and should be investigated before any merge review.
- `main` remains unchanged by this audit.

### Remaining verification boundaries
- Guest expiry/export needs a browser-level test with a disposable guest profile and controlled clock.
- Offline shell behavior and local draft persistence need a real browser/device test; cloud sync must be tested after reconnection with disposable accounts.
- Two-account isolation, project save/reload/restore, tombstone recovery, AI Companion history integrity, and messaging/notification ownership still need disposable end-to-end tests.
- Live Supabase migration history, effective grants/RLS, bucket settings, Render configuration and production user data have not been inspected in this pass.
- No live Supabase changes, SQL execution, provider calls, billing actions, PR merge, or production deployment were performed.
