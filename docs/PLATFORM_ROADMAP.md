# PWA Studio — platform roadmap

Updated: 2026-11-20

## Product direction

PWA Studio is a multi-user creative platform with a public guest-facing area, private creator workspaces, an owner/admin area, a Mini Movie Studio, a personal media library, and safety/moderation controls. The product should support both stylized animation and cinematic photorealism/CGI, including consistent fictional characters and consent-based digital doubles.

## Current state (verified in repository)

- Public browsing is available without forcing the login dialog.
- Supabase Auth sign-in, sign-up and password reset email flow are present in the frontend.
- A personal-account screen has been added. It displays the signed-in user's profile and links to their creative areas.
- A separate owner panel is shown only after the backend confirms the account role.
- Mini Movie Studio exists. Film drafts are still stored in browser localStorage, now namespaced by Supabase user ID.
- Rules and safety page has been added to the public interface.
- Backend AI chat and prompt-generation routes now require a valid Supabase access token.
- The backend has an initial text safety guard for a limited set of clearly harmful request patterns.
- A Supabase migration has been added for private storage buckets, per-user storage policies, moderation reports and an admin audit log.
- PWA shell cache has been bumped to v10.

## Important gaps — do not describe these as finished

- The live Supabase schema was created earlier through SQL Editor. Compare it with the repository's original 0001_initial_schema.sql before running any older migration. Do not rerun 0001 blindly.
- The new 0002_storage_and_moderation.sql has been committed but has NOT been run in Supabase. Storage buckets and report/audit tables therefore are not yet confirmed live.
- No cloud project CRUD API exists yet. Project data is not yet reliably synchronized across devices.
- No actual file upload/download UI is connected to Supabase Storage.
- No real video-generation provider is connected. DeepSeek currently handles text AI only.
- No photorealistic character training, identity consistency, voice cloning or CGI rendering pipeline is connected.
- The text safety guard is only a first layer. It is not comprehensive moderation and does not inspect images, video, audio or generated output.
- The report form, moderation queue, user restrictions, appeals and full audit workflow still need implementation.
- Password recovery still needs a secure new-password screen after the email callback.
- Owner DB role and backend owner role must be reconciled and verified; never trust a role value supplied by the browser.

## Target architecture

### Roles and access

1. Guest: browse landing pages, guide and rules; cannot use authenticated generation or save private work.
2. Creator: private projects, characters, scenes, media and voice assets; can submit reports and manage own account.
3. Owner/admin: manage platform settings and users, review reported/flagged content, apply proportionate restrictions and record every moderation action.

Default privacy: creator projects are private. Admin access to user content is limited to reported/flagged material and legitimate moderation needs, with audit logging. Avoid unrestricted browsing of every private project.

### Cloud persistence

- Supabase Auth: identities and sessions.
- PostgreSQL: profiles, projects, characters, scenes, prompt metadata, media metadata, moderation reports and audit events.
- Supabase Storage (initial option): private buckets studio-media and studio-exports.
- Object key convention: <auth-user-uuid>/<project-id>/<asset-name>.
- FastAPI: validates JWT, enforces role and ownership, creates project metadata, issues safe upload/download access where appropriate, coordinates AI providers.
- Later, move large media/exports to an S3-compatible object store if storage, bandwidth or cost requires it.

Do not store video binaries in PostgreSQL or localStorage. Store metadata in the database and file bytes in object storage. Add quotas, MIME/type validation, size limits, lifecycle cleanup, backups and signed downloads.

### Mini Movie Studio

The target workflow:
1. New film and project settings.
2. AI-assisted script and storyboard.
3. Character creation from text or consented reference images.
4. Character bible: appearance, wardrobe, voice, personality and continuity notes.
5. Scene planning and shot list.
6. Generate one or more scene takes through external video/image providers.
7. Review and regenerate a single scene without discarding the rest.
8. Timeline editing: video, voice, music, subtitles, transitions.
9. Preview and render.
10. Save editable project, versions and exports.

Offer a simple guided mode and an advanced director mode. Support photorealistic cinema, realistic CGI/digital humans, 2D/3D animation, anime, illustration and custom looks. Keep model/provider capability and cost visible; never promise a particular fidelity before testing.

### Digital characters and consent

- Character profile stores description, reference asset IDs, continuity prompt, approved voice ID and project links.
- Reuse one character across scenes and films.
- For a user's own likeness, require an explicit confirmation that they own or are authorized to use the submitted photo/voice.
- For another real person, require documented permission before face/voice replication.
- Do not create non-consensual intimate imagery, deceptive impersonation, harassment or fraud.
- Keep source photos/voice samples private, restrict access and provide deletion controls.
- Prefer provider APIs with explicit consent and identity safeguards; do not train a model on a person's likeness without clear authorization.

### Safety and moderation

Layered safeguards:
1. Public rules and clear notices.
2. Authenticated access for creation and generation.
3. Input text checks and provider safety settings.
4. Image/video/audio moderation before publication or sharing.
5. User report form and automated risk flags.
6. Admin review queue with minimal necessary access.
7. Graduated actions: warning, content restriction, temporary suspension, permanent ban for severe/repeated violations.
8. Appeal path and transparent user notification.
9. Append-only moderation audit events.
10. Periodic tests for false positives, missed harmful requests and privacy leakage.

The initial regex guard must not be treated as a substitute for the above system.

## Implementation sequence

### Phase A — account and policy foundation
- [x] Add personal-account and public rules pages.
- [x] Separate local film drafts by account ID.
- [x] Require sign-in for AI chat and prompt generation.
- [x] Add initial backend text safety guard.
- [x] Add storage and moderation SQL migration file.
- [ ] Run/review the migration in Supabase and verify bucket policies.
- [ ] Verify the owner account role in backend and database.
- [ ] Test guest, creator and owner flows on the live site.
- [ ] Complete password recovery.

### Phase B — cloud projects and media
- [ ] Build authenticated project CRUD endpoints with ownership checks.
- [ ] Connect the Mini Movie Studio to cloud project records.
- [ ] Connect secure file upload, listing, download and delete.
- [ ] Add per-user storage quotas and cleanup.
- [ ] Add project versions and asset references.

### Phase C — moderation operations
- [ ] Build report submission UI.
- [ ] Build owner-only moderation queue and item review.
- [ ] Add restriction/suspension actions and appeal process.
- [ ] Record every admin action in audit events.
- [ ] Add multimodal moderation for uploaded and generated media.

### Phase D — cinematic creation
- [ ] Select and test video-generation providers and pricing.
- [ ] Build provider adapter layer; keep provider keys on backend only.
- [ ] Implement character library and consent workflow.
- [ ] Implement scene-level generation, variants and regeneration.
- [ ] Add voice, soundtrack, subtitles and timeline.
- [ ] Add render queue, progress tracking and MP4 export.

### Phase E — scale and reliability
- [ ] Background jobs and retry/resume for long renders.
- [ ] Storage monitoring, backups, quotas and lifecycle rules.
- [ ] Usage metering and cost controls.
- [ ] Security review, load testing and launch checklist.

## Next concrete actions

1. Verify the new frontend pages and account flows on GitHub Pages.
2. Run a syntax/deployment check for the updated FastAPI backend on Render.
3. In Supabase, review and then run 0002_storage_and_moderation.sql; do not rerun 0001 blindly.
4. After confirming the live schema and owner role, implement cloud project APIs and media upload.
