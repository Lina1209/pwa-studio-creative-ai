# PWA Studio — implementation roadmap and status

Last reviewed: 2026-11-22

For the complete product vision, platform rules, prohibited-content taxonomy, filters, bans, appeals, privacy/security requirements, rights/consent, testing strategy, and phased plan, see [ARCHITECTURE_SECURITY_AND_PRODUCT_PLAN.md](./ARCHITECTURE_SECURITY_AND_PRODUCT_PLAN.md).

This document is the working source of truth for the next implementation stages. It distinguishes deployed/verified behavior from UI prototypes and planned work. A database migration in this repository is **not** considered applied to the live Supabase project until it has been run and verified there.

## Verified foundation

- Frontend: Vanilla JavaScript / HTML / CSS, deployed through GitHub Pages.
- Backend: FastAPI on Render.
- Authentication and database: Supabase Auth and Postgres.
- AI provider: DeepSeek through LiteLLM.
- AI Companion chat endpoint responds successfully.
- AI usage telemetry writes to `public.ai_usage`; a real row was verified on 2026-11-21 (provider `deepseek`, model `deepseek-flash`, token counts and cost recorded).
- The live database required an explicit `GRANT INSERT ON TABLE public.ai_usage TO service_role`; the privilege check returned true.
- AI Companion history is connected to Supabase; a new conversation and both messages were visible after a browser refresh on 2026-11-21. RLS owner policies are present; logout/login, account-switch behavior, and two-account isolation still require end-to-end verification.
- Mini Movie Studio has a local-first cloud sync implementation in `app.js`. Migration `0005_cloud_projects_and_storage.sql` was applied to live Supabase; `public.projects` and the private `studio-media` bucket were verified. A test movie row was independently confirmed in Supabase and remained visible after browser refresh. Cross-device persistence, conflict behavior, and deletion synchronization still require verification.
- Audio Studio has a navigable UI and local microphone/file preview only. It does not yet upload media or call speech/music generation services.

## Workstreams and acceptance criteria

### 1. AI Companion persistent history
**Current state:** migration `0004_assistant_chat_history.sql` was applied to live Supabase. Frontend saves and reloads conversation titles and user/assistant messages. A test conversation survived a browser refresh on 2026-11-21. Migration `0006_assistant_conversation_updated_at.sql` has been added to keep conversation ordering correct after a rename; it has not been applied to the live database.

Remaining verification: test logout/login and confirm that a second account cannot read or modify the first account's conversations. Existing AI replies continue to work.

### 2. Cloud project and media persistence
**Current state:** local-first cloud sync code targets `public.projects`. Migration `0005_cloud_projects_and_storage.sql` has been applied and verified in live Supabase; the table, owner policies, private `studio-media` bucket, and a real test project row were checked. The project remained visible after browser refresh. Cross-device sync and deletion/conflict behavior are not yet verified. No media upload UI exists yet.

Next tasks:
1. Test create, edit, rename, copy, and delete flows against Supabase; verify same-account cross-device persistence.
2. Test conflict behavior and deletion synchronization without losing local drafts; review tombstone/restore behavior.
3. Add a media library upload/list/delete UI using the private bucket; validate file size and MIME type in the client and enforce Storage limits/RLS server-side.
4. Add media metadata records and signed URL previews; never make user media public by default.

Done when: cloud projects survive across devices, owner isolation is verified with two accounts, and private media can be uploaded and retrieved only by its owner.

### 3. Audio Studio
**Current state:** six-section UI; local microphone recording and audio-file preview only. No server upload or model calls.

Tasks:
1. Keep the current interface intact while separating local preview from cloud actions.
2. Implement secure upload to private storage and user-owned audio assets.
3. Add provider-neutral backend job interfaces for text-to-speech, music, sound effects, and voice workflows.
4. Add job status, cancellation/timeouts, quota/cost metering, and clear error states.
5. Treat voice cloning as a separate consent-gated feature: verify the speaker's authorization, keep samples private, and provide deletion controls.
6. Add editing/mixing only after a stable media asset model exists.

Done when: a user can upload/record, securely store, generate or process supported audio, preview it, and export it with usage tracked.

### 4. Character Library
**Current state:** a `studio_characters` table is reported in the existing database foundation; the full workflow is not implemented or verified.

Tasks:
1. Inspect the actual schema and RLS policies before relying on the table.
2. Build owner-scoped character CRUD and private reference-image storage.
3. Store reusable character descriptions, visual references, continuity notes, and consent/provenance metadata.
4. Add provider adapters for character/reference image generation only after choosing supported providers.
5. Add scene-level character reuse and consistency controls.

Done when: a user can save, edit, reuse, and delete their own characters across projects, without cross-account access.

### 5. Video generation and production pipeline
**Current state:** production planning/editor UI and local notes exist; video generation, timeline rendering, and MP4 export are not connected.

Tasks:
1. Define provider-neutral video job and asset interfaces.
2. Add server-side provider credentials only; never expose keys in frontend code.
3. Implement queued jobs, polling/webhooks, retries, cancellation, failure handling, and cost metering.
4. Link scene prompts, character references, generated clips, audio, and project versions.
5. Implement timeline assembly and export after media contracts are stable.
6. Test provider terms, rights, safety, retention, and per-user quotas before public launch.

Done when: a project can generate scene assets, assemble a timeline, and export a playable film with ownership and usage records.

### 6. Site analytics and Live World
**Current state:** concept only; no verified visitor analytics implementation.

Tasks:
1. Define privacy-preserving first-party event collection and retention.
2. Count page visits separately from approximate unique browsers; do not claim exact human identity.
3. Count registered accounts from Supabase Auth using a server-side trusted query.
4. Track approximate active sessions with short-lived heartbeats and expiry.
5. Track peak concurrent sessions and daily/overall totals without exposing personal data.
6. Add optional country-level geolocation only from a trusted privacy-reviewed source; never store precise location or expose IP addresses.
7. Build the statistics panel and globe only after data quality and privacy rules are settled.
8. Exclude known bots where feasible and label all visitor figures as estimates.

Done when: totals persist across deploys, refreshes do not inflate unique visitors, active counts expire correctly, and public output contains aggregates only.

### 7. Community chat and moderation
**Current state:** concept only; no verified public chat implementation.

Tasks:
1. Design channels/messages, membership, reports, moderation actions, and audit history.
2. Require authenticated accounts to post; optionally allow guests to read only if explicitly configured.
3. Enforce all permissions in Postgres RLS and/or backend authorization, not merely by hiding UI controls.
4. Support message deletion, user mute/temporary ban/permanent ban, unban, report review, pinning, and chat lock.
5. Make administrator identity derive from the trusted server-side admin configuration/role; never accept an admin flag from the browser.
6. Add rate limits, spam/link controls, retention policy, and abuse-report handling.
7. Keep community chat separate from private AI Companion conversations.

Done when: users can chat safely, moderation is enforced server-side, and admin actions are auditable.

## Recommended implementation order

1. Stabilize current foundation: account switching, AI context/isolation, admin authorization, Mini Movie Studio labels, version restore, cloud conflict/deletion behavior.
2. Build private media upload and asset metadata on the already-applied Storage foundation.
3. Verify schema/RLS and build Character Library.
4. Implement platform rules, backend safety filters, moderation, reports, bans, appeals, and audit controls before opening community posting or unrestricted generation.
5. Build Audio Studio upload and provider/job framework.
6. Build image/video provider/job pipeline and then timeline/export.
7. Implement privacy-preserving visitor analytics and Live World.
8. Implement community chat after moderation controls are enforceable.
9. Complete quotas, billing, rights/privacy review, and launch readiness.

## Release and safety rules

- Work in small commits and verify each change before proceeding.
- Never put Supabase service-role keys or AI provider keys in frontend code, GitHub, or chat.
- Do not apply migrations blindly to production; inspect live schema first and apply one reviewed migration at a time.
- Preserve existing local drafts and user content during cloud migration.
- Enforce ownership and admin privileges server-side and with database policies.
- Record AI/media usage and enforce quotas server-side before opening paid features.
- Obtain explicit consent for voice cloning and use of real people's likenesses.
- Clearly distinguish implemented, prototype, and planned features in the UI and documentation.


## Platform rules and moderation

The detailed policy and moderation plan is maintained in [ARCHITECTURE_SECURITY_AND_PRODUCT_PLAN.md](./ARCHITECTURE_SECURITY_AND_PRODUCT_PLAN.md), including policy taxonomy, layered filters, enforcement ladder, temporary/permanent bans, appeals, audit logging, and privacy requirements. These capabilities are planned and must be enforced server-side; frontend-only filters or hidden buttons do not count as security.


## 10. Durable jobs and credit ledger — design prepared

The design contract is documented in [GENERATION_JOBS_AND_LEDGER_DESIGN.md](./GENERATION_JOBS_AND_LEDGER_DESIGN.md).

Current status: design only. No Redis/Celery dependency, worker, job tables, wallet, holds, ledger, or real billing has been deployed. The next implementation step is to define the first provider-backed operation and job/asset contract, then add the database job/outbox schema with ownership/RLS and automated SQL tests. Credit wallet and ledger RPCs follow after transaction semantics and pricing assumptions are reviewed. Existing `ai_usage` remains telemetry only and must never be treated as a credit balance.
