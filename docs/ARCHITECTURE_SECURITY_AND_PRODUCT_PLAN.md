# PWA Studio — Architecture, Safety, Governance and Product Plan

Last reviewed: 2026-11-23

This is the cross-project planning document for PWA Studio. It records product intent, current evidence, security and moderation requirements, known gaps, and the recommended implementation sequence. It complements `IMPLEMENTATION_ROADMAP.md`; it does not claim that planned work is implemented.

## 1. Product vision

PWA Studio is an independent, mobile-friendly creative AI workspace for developing stories and prompts, planning films, creating and reusing characters, generating images/video/audio, editing media, and exporting finished work. It also includes a private AI Companion and may include a separately moderated community.

Product principles:
- Preserve the existing visual identity and working user flows; improve incrementally rather than replacing working sections.
- Make the distinction between prototype, implemented, deployed, and verified visible and honest.
- Keep user projects private by default and enforce ownership on the server/database.
- Keep provider credentials on the backend.
- Design provider-neutral job and asset contracts so models can be changed without rebuilding the product.
- Track real usage and costs before enabling quotas or paid plans.
- Treat safety, privacy, accessibility, rights, and moderation as product foundations, not last-minute additions.

## 2. Evidence labels

Use these labels in issues, commits, UI copy, and release notes:
- **Verified live** — exercised against the deployed application or live service, with a concrete result.
- **Implemented, not fully verified** — code exists but relevant integration, account isolation, cross-device, failure, or security tests remain.
- **Prototype/UI only** — interface or local-only behavior exists; no production backend capability.
- **Planned** — not implemented.
- **Blocked** — cannot proceed until a named dependency or decision is resolved.

A committed migration is not proof it has been applied. A successful browser refresh is not proof of cross-device synchronization. A preview is not proof of restore. A visible admin control is not proof of server-side authorization.

## 3. Current architecture and verified baseline

### Frontend
- Vanilla JavaScript, HTML and CSS with Tailwind-related styling.
- Hosted through GitHub Pages.
- PWA shell/service-worker work exists; installation, offline behavior, cache updates, and recovery need a device/browser test matrix.

### Backend
- Python / FastAPI hosted on Render.
- LiteLLM routes AI requests to DeepSeek.
- JWT verification uses Supabase signing keys and validates issuer, audience, expiry, and subject.
- Admin identity is derived server-side from the verified Supabase JWT subject UUID matching OWNER_USER_IDS; email is display/contact data only. The UUID allowlist must be configured in hosting secrets before owner access is available.
- Provider credentials must remain in Render environment variables.

### Supabase
- Supabase Auth and Postgres are connected.
- `public.ai_usage` telemetry was verified with a real row, including provider/model, token counts, and cost.
- Migration `0004_assistant_chat_history.sql` was applied; conversation and message tables exist and a test conversation survived browser refresh.
- Migration `0005_cloud_projects_and_storage.sql` was applied and verified: `public.projects` exists and private `studio-media` bucket exists. Owner-scoped policies were inspected.
- A test movie project was confirmed in `public.projects` and remained visible after page refresh.
- Cross-device sync and two-account isolation remain unverified.
- No production media upload/list/delete UI is connected to the bucket yet.

### AI Companion
- Chat endpoint responds successfully.
- Conversation/message persistence, history list, create/rename/load, and refresh persistence are implemented.
- Remaining: logout/login, account-switch reset, two-account isolation, context-window behavior, error recovery, and confirmation that prior messages are actually supplied to the model on subsequent turns.

### Mini Movie Studio
- Project creation, details editing, rename, copy, delete, staged planning workflow, draft saves, previous/next navigation, version previews, and restore action exist in the frontend.
- The four production sheets are scenario/storyboard, characters, voices/sound, and edit/export plan; basic details are a separate first sheet.
- Test materials for all four production stages survived refresh and reopening.
- All 13 version previews were opened during manual testing; their stage counts and scenario previews were consistent. The current project remained at 0/4 after closing history, and a backup copy remained in the collection.
- Version restore itself has not been independently tested.
- Video generation and real MP4 export are not connected.
- Known UI debt: production-sheet numbering currently says 1–4 even though basic details is a separate first sheet; use consistent 2–5 of 5 labels. Avoid wording such as “ready film” where only planning materials are complete.

### Audio Studio
- Navigable UI, local microphone recording, and local file preview exist.
- Selected/recorded audio is not uploaded to the server; no TTS/music/SFX provider workflow or full editing/mixing is connected.

### Character Library, analytics, community
- Character reference-storage and visual-metadata migrations exist in the review branch; full owner-scoped character CRUD and live RLS verification remain incomplete.
- First-party visit analytics and privacy-governance foundations exist in the review branch; production collection, retention, legal review and public aggregate behavior remain unverified.
- Community chat and public moderation remain planned.
- A private support inbox is implemented in the review branch (user ticket UI, owner inbox, FastAPI routes, scoped capabilities and audit events); migrations 0055/0091 are not live and the flow is not production-verified.
- No public creator showcase/gallery is implemented; it is now a separate planned product surface.

## 4. Product modules and target capabilities

### A. AI Companion and Prompt Studio
- Private conversations, conversation management, persistent messages, safe context assembly, prompt creation/improvement/translation/adaptation, reusable prompt library.
- Clear separation between user content and trusted system instructions.
- Server-side input validation, moderation, rate limits, quotas, and usage records.
- Context assembly must use only the authenticated user's own conversation history and a bounded, documented token budget.

### B. Mini Movie Studio
- Film/project metadata and staged planning.
- Story, scenes, storyboard, characters, voice assignments, sound, edit plan, version snapshots.
- Project autosave with visible save state, conflict handling, restore confirmation, backup/export, and cloud sync.
- Future generation jobs connect scenes to image/video/audio assets and timeline items.
- UI must never imply a playable/exported video exists until a real render has completed and the output has been verified.

### C. Media Library
- Private uploads, listing, preview via short-lived signed URLs, metadata, deletion, storage quotas, MIME/size validation, ownership enforcement.
- Use object paths scoped to authenticated user IDs; do not make private user assets public by default.
- Define retention, orphan cleanup, and deletion propagation.

### D. Character Library
- Owner-scoped create/read/update/delete.
- Description, appearance, wardrobe, traits, continuity notes, reference images, provenance and consent metadata.
- Reuse across projects and scenes without cross-account leakage.
- Distinguish fictional characters from real-person likeness workflows.

### E. Audio Studio
- Upload and record audio to private storage.
- TTS, music, sound effects, voice profiles, audio preview, trim/mix/volume/fade and export as provider capabilities permit.
- Voice cloning is a separately gated high-risk feature: explicit speaker authorization, proof/attestation workflow appropriate to risk, private sample storage, clear permitted use, audit trail, revocation/deletion, and abuse response.
- Do not imply voice cloning exists until the end-to-end provider and consent flow is implemented and tested.

### F. Image/video generation and production pipeline
- Provider-neutral adapters, server-side credentials, job queue, status polling/webhooks, retries, timeouts, cancellation, idempotency, cost/usage records.
- Scene prompts, reference images, characters, generated clips, audio, timeline, subtitles/titles, aspect ratio, resolution, and export settings.
- Validate provider terms, content policies, output rights, retention, and regional availability before enabling a provider.
- Export must produce a real playable file; verify duration, codec/container, audio/video sync, dimensions, and download/access controls.

### G. Analytics and Live World
- First-party privacy-preserving event collection.
- Separate page views, approximate unique browsers, registered accounts, guest sessions, active sessions, daily aggregates, and peak concurrent sessions.
- Label estimates accurately; bots/search crawlers should be excluded or separately classified where feasible.
- No public IP addresses, precise location, or identifiable visitor trails. Country-level aggregation only after privacy review and with an appropriate trusted source.
- Retention limits, access control, consent/legal review where required, and aggregate-only public display.

### H. Community and moderation
- Separate from private AI Companion conversations.
- Authenticated posting by default; guest read access only if explicitly chosen.
- Persistent messages, edit/delete own message, report, pin, channel open/close, moderator review, admin deletion, mute, temporary/permanent ban, unban, appeals, audit log.
- Enforce every permission in backend/database policies. Hiding a button is not authorization.
- Rate limits, anti-spam controls, link controls, report queue, escalation and moderator guidance.

### I. Support and feedback inbox
- Private, asynchronous user-to-administration conversations, separate from AI Companion and public community chat.
- Categories for general help, bugs, account/access, billing/credits, feature requests, product feedback and safety/privacy.
- User-owned ticket list and message history; owner-only queue, reply and status controls.
- Atomic ticket-plus-first-message and message-plus-status database operations.
- Optional, user-approved diagnostic context; never attach private prompts, project contents, credentials or media by default.
- Status lifecycle: open, in progress, waiting for user, resolved and closed; first-response and resolution timestamps.
- Admin reads and mutations are permission-gated and audited.
- Later additions: unread notifications, verified transactional email, assignment, priority, internal notes, attachments through private storage, saved replies and SLA metrics.
- Private feedback is the default. Public idea voting requires a separate opt-in board and moderation controls.

### J. Inspiration and creator showcase
- A guest-facing inspiration page with platform-owned demos, prompt explanations, starter templates and example workflows.
- A separate opt-in gallery for user-published works: films, images, music/sound, voiceover, scripts, storyboards and prompts.
- Private projects and assets remain private unless a user explicitly publishes a selected item.
- Creator attribution, explicit display/remix/template permissions, publication history, unpublish and takedown.
- Search, filters, collections, likes/bookmarks and “use as template” copy semantics.
- Public publication must use controlled preview assets and moderation; it must not make the user's private Storage bucket public.
- A paid marketplace is deferred until licensing, creator verification, payout, tax, dispute and fraud workflows are ready.


## 5. Platform rules, prohibited content, filters, bans and appeals

This is a required launch workstream, not optional polish.

### 5.1 Rules and policy set
Create and publish clear, versioned documents:
1. Terms of Service / acceptable use.
2. Community Guidelines.
3. AI generation and content policy.
4. Privacy notice and data-retention/deletion policy.
5. Copyright, user content, AI output, and third-party provider terms summary.
6. Voice/likeness and impersonation policy.
7. Moderation, enforcement, and appeals procedure.

Policies must be understandable, localized as needed, and consistent with provider terms and applicable law. Record policy version and acceptance where legally/product appropriate. Do not claim legal compliance without qualified review.

### 5.2 Policy taxonomy
Use a severity-based taxonomy rather than one broad “taboo word” list:
- **Disallowed**: content or requests that must be blocked under law, platform rules, or provider policy.
- **Restricted / gated**: content allowed only under age, consent, account, or feature restrictions.
- **Allowed with safeguards**: sensitive but legitimate creative, educational, historical, journalistic, or support content.
- **Allowed**: ordinary creative content.
- **Uncertain / context required**: route to a safer clarification, refusal, or human review instead of silently imposing a permanent penalty.

Maintain separate rules for text, image, video, audio, voice, real-person likeness, and community conduct. The exact categories and thresholds must be finalized against provider terms and legal review.

### 5.3 Layered filtering architecture
1. **Frontend preflight** — friendly warnings and obvious mistakes; never the only enforcement layer.
2. **Backend request validation** — authentication, size/type/schema validation, rate limits, policy checks before provider calls.
3. **Provider safeguards** — retain and respect provider moderation and policy responses; do not attempt to bypass them.
4. **Output checks** — inspect generated text/media where technically supported before delivery or publication.
5. **Community moderation** — report queue, automated signals, moderator/admin review, audit trail.
6. **Abuse monitoring** — repeated attempts, spam, evasion patterns, unusual usage, and account compromise signals.

Filters must be context-aware. Keyword matching alone is insufficient and can create false positives. Consider obfuscation, homoglyphs, spacing, transliteration, language variants, quoted material, negation, and benign educational/fictional context. Do not promise perfect detection. Provide safe explanations and a path to appeal.

### 5.4 Enforcement ladder
Possible actions, selected proportionately:
- allow;
- warn or ask for clarification;
- block one request with an explanation;
- temporary feature restriction;
- temporary mute from community;
- temporary account suspension;
- permanent account ban for severe/repeated abuse;
- remove content or disable access to a specific asset where justified.

Requirements:
- Human review for consequential or ambiguous sanctions where feasible.
- Clear reason code, policy section, timestamp, scope, duration, and moderator identity for each action.
- Ban expiry and automatic unban for temporary sanctions.
- Admin/moderator actions require server-side role checks.
- Protect against self-escalation and unauthorized moderator actions.
- Provide appeal intake, review status, outcome, and audit history.
- Never expose sensitive reporter information to the reported user.
- Define emergency escalation and account-security recovery separately from ordinary moderation.

### 5.5 Ban and moderation data model (design target)
Proposed entities, subject to schema review:
- `policy_versions`: version, locale, effective date, document reference.
- `moderation_reports`: reporter, target type/id, reason, evidence reference, status, timestamps.
- `moderation_cases`: case owner, severity, decision, rationale, status.
- `moderation_actions`: target user/content, action type, scope, start/end, reason code, actor, appeal state.
- `user_restrictions`: active restriction lookup with expiry and enforcement scope.
- `moderation_audit_log`: append-only record of privileged actions.
- `user_appeals`: appeal reason, linked action, reviewer, outcome, timestamps.
- `filter_events`: minimal event metadata for policy tuning; avoid retaining raw sensitive prompt text unless strictly necessary and disclosed.

Use RLS and backend authorization carefully. Ordinary users must not be able to create or edit their own ban status, reports' moderation outcomes, audit records, or admin roles. Consider separate privileged server functions and least-privilege database grants. Avoid storing unnecessary personal data.

### 5.6 Filter quality and governance
- Maintain a versioned policy/rule set with test fixtures.
- Test supported languages, misspellings, obfuscation, quoted text, educational context, fiction, and benign lookalikes.
- Measure false positives and false negatives; review samples under privacy controls.
- Keep an emergency kill switch for a faulty rule deployment, restricted to authorized administrators.
- Log rule version and decision code, not secrets.
- Do not train or tune filters using private user content without a clear lawful basis, transparency, and appropriate controls.

## 6. Identity, security and privacy requirements

- RLS for every user-owned table and private storage object.
- Verify ownership server-side for every read/write that bypasses a user's Supabase session.
- Never trust browser-supplied role, owner ID, cost, quota, moderation decision, or provider result.
- Keep service-role and provider keys in server secrets only; rotate if exposed.
- Use least-privilege database grants; verify privileges as well as RLS policies.
- Rate-limit login, chat, prompt generation, uploads, generation jobs, and reports.
- Validate MIME type and actual file signatures where feasible; enforce size, duration, and count limits.
- Use short-lived signed URLs for private media.
- Add CSRF/origin protections where relevant, secure headers, dependency updates, and secret scanning.
- Minimize telemetry and logs; never log passwords, tokens, secret keys, or unnecessary raw user content.
- Define account export/deletion, project/media deletion, retention, backup, and incident-response procedures.
- Test account switching so in-memory conversation/project IDs and UI state are reset before loading another user's data.

## 7. Usage, quotas and monetization

Existing: AI token/cost telemetry is working for tested requests.

Not yet complete: user-facing credits, free quotas, paid plans, enforcement, billing lifecycle, refunds, and reconciliation.

Design:
- Guest preview with strict duration, output, and resource caps.
- Registered free tier with explicit daily/monthly allowances.
- Paid tiers with clear limits and included capabilities.
- Optional weekly/monthly subscriptions only after provider costs and payment operations are understood.
- Server-side usage ledger and atomic quota reservation/settlement; never trust client counters.
- Track provider, model, job type, tokens/seconds/credits, estimated and actual cost, status, and user/project.
- Handle failed, cancelled, retried, and partially completed jobs without double charging.
- Alerts and hard spending caps at provider/account level where available.
- Explain that third-party model availability, output rights, and commercial use can vary by provider and plan.

## 8. Rights, consent and content provenance

- Preserve user ownership/rights in uploaded source material subject to applicable law and service terms.
- Explain that AI output rights and commercial-use permissions depend on jurisdiction, provider terms, model, and plan; do not promise universal copyright ownership.
- Store provider/model/version, generation time, prompt/reference linkage, and license/terms snapshot where feasible.
- Require users to confirm they have rights to upload reference material and permission to use real people's likenesses/voices.
- Special consent gates for voice cloning and realistic impersonation.
- Provide deletion and revocation workflows for voice samples and likeness references.
- Publish clear takedown/report procedures and a contact route after legal review.

## 9. Quality, reliability and testing

Minimum test layers:
- Unit tests for policy rules, cost/quota arithmetic, project serialization, version snapshots, and access decisions.
- API tests for authentication, owner isolation, admin-only actions, validation, rate limits, and error handling.
- Database tests for RLS, grants, triggers, storage policies, and migration idempotency.
- End-to-end tests for signup/login/logout/account switch, AI history, project create/edit/rename/copy/delete/restore, uploads, generation jobs, and export.
- Cross-device tests using the same account; cross-account tests using separate accounts.
- Mobile tests on Android Chrome, including slow network, refresh, offline shell, storage pressure, and interrupted uploads.
- Backup/restore and incident recovery drills before public launch.

Each feature needs explicit acceptance criteria and evidence. Manual user testing should be guided one step at a time and avoid destructive actions without a backup.

## 10. Prioritized implementation plan

### Phase 0 — documentation and source-of-truth (now)
- Keep this document and the implementation roadmap aligned.
- Correct outdated statements about migration 0005 and verified cloud project creation.
- Maintain a status register and change log after each substantial work session.

### Phase 1 — stabilize current foundation
1. Audit account switching and clear stale AI Companion state.
2. Verify actual AI conversation context passed to the model.
3. Test logout/login and two-account isolation.
4. Verify admin role configuration and protected endpoints.
5. Fix Mini Movie Studio 2-of-5 through 5-of-5 labels and misleading “ready” wording.
6. Test version restore using a backup and explicit confirmation.
7. Audit cloud sync conflict, tombstone deletion, retries, and cross-device behavior.
8. Inspect live schema and RLS for all existing tables, including character-related tables.
9. Update README and roadmap from verified evidence.

### Phase 2 — secure shared asset foundation
1. Media asset metadata schema and private upload/list/delete UI.
2. Signed preview URLs and cleanup of orphaned objects.
3. Upload validation, limits, progress, retry, and cancellation.
4. Owner-isolation and cross-device tests.
5. Character Library CRUD and private reference images.

### Phase 3 — rules, filters and moderation
1. Finalize policy taxonomy and user-facing rules.
2. Implement backend moderation gateway for every generation endpoint.
3. Add safe explanations, audit events, appeals, and admin controls.
4. Add community reporting, mute/ban/unban, and moderator audit.
5. Add multilingual/obfuscation regression tests and false-positive review.

### Phase 4 — Audio Studio
1. Secure audio upload and asset records.
2. TTS, music, and SFX provider adapters.
3. Job lifecycle, metering, quotas, cancellation, and failure states.
4. Consent-gated voice workflows.
5. Audio editing/mixing and export.

### Phase 5 — image/video pipeline and editor
1. Select providers based on quality, terms, cost, availability, and safety.
2. Implement job queue and scene asset workflow.
3. Generate images/clips and preserve character consistency.
4. Build timeline, captions, transitions, audio mixing.
5. Render and validate playable MP4 outputs.

### Phase 6 — community, analytics and Live World
- Implement community chat only after moderation, reports, bans, and admin controls are enforceable.
- Implement privacy-reviewed aggregate analytics and optional country-level globe.
### Phase 6A — private support and feedback
- Verify the review-branch support inbox and migrations 0055/0091 before live application.
- Add support launcher, user notifications, admin queue filters and internal notes.
- Add private feedback intake and later an opt-in public idea board.

### Phase 6B — inspiration and creator showcase
- Publish platform-owned examples and starter templates.
- Add opt-in user publication, attribution, license choices, moderation, takedown and unpublish.
- Keep a paid creator marketplace out of scope until creator-rights and payout operations are ready.


### Phase 7 — monetization and public launch
- Complete quotas, payment integration, cost controls, legal documents, privacy/security review, support and incident processes.
- Run acceptance tests and publish a truthful feature/limitations page.

## 11. Current known gaps and cautions

- AI Companion cross-account isolation and account-switch behavior are not yet tested.
- Confirm that previous conversation turns are included in model context; database persistence alone does not prove conversational memory.
- Migration 0005 and the storage bucket are live and verified; media upload UI is not implemented.
- Cloud project creation was verified in Supabase and after refresh; cross-device sync is not yet verified.
- Deletion sync/conflict handling requires focused testing before relying on it.
- Version previews were checked; restore behavior has not yet been tested.
- Stage text survived refresh/reopening; do not claim every stage's latest content was independently SQL-verified.
- Character table/schema/RLS must be inspected before building on it.
- Audio is local preview only.
- No real image/video generation pipeline, audio generation pipeline, timeline renderer, or MP4 export is connected.
- Visitor analytics and privacy-governance code exists in the review branch but is not live-verified; community chat, full moderation, ban/appeal system and creator showcase remain planned.
- The support inbox exists in the review branch but is not deployed or live-verified; no real-time delivery, email/push notifications, attachments, assignment, internal notes or queue filters are connected yet.
- No concrete production video-provider adapter is present; the provider idempotency audit marks video generation blocked.
- Audio remains local preview only; speech-to-text, text-to-speech, music/SFX provider calls, dubbing, lip-sync, voice library, mixing and export are not connected.
- Wallet, quota and payment foundations in the review branch are not equivalent to an enabled payment provider or production billing; payment execution remains disabled.
- Existing keyword safety checks are only a first layer; they are not a complete moderation system.

## 12. Working agreement

- Work in small, reviewable commits.
- Before editing a working flow, inspect the current code and preserve user data.
- For database changes: inspect live schema, prepare one migration, review it, apply it, then verify tables, policies, and behavior.
- Never ask the user to paste secret keys into chat.
- Do not claim deployment or production behavior from a GitHub commit alone.
- Record what changed, commit SHA, deployment status, and verification evidence.
- When user testing is needed, give one clear action at a time and wait for the result.
- Keep the existing visual style unless the user explicitly requests a redesign.
