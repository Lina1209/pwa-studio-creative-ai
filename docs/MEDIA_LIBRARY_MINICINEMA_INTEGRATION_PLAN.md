# Media Library → Mini Cinema Integration Plan

Status: engineering plan only; no production schema or runtime behavior changed.

## Goal

Connect the existing Mini Cinema project workflow to a canonical, owner-scoped Media Library without breaking current project records, local drafts, version history, or cloud synchronization.

The first milestone is deliberately narrow: a signed-in owner can view their ready media assets, attach an existing asset to a Mini Cinema project, inspect where it is used, and detach it safely. Guest work remains local until the user explicitly exports or imports it.

## Current source-code baseline

- Mini Cinema projects currently use browser-side project state and an authenticated cloud synchronization path to `public.projects`.
- Cloud project records contain project metadata/settings; they are not a canonical binary-media store.
- Guest projects remain device-local and have an expiry/export workflow. No automatic guest-to-account migration was identified.
- The current Media Library screen is a placeholder; a complete upload/asset API and server-side asset lifecycle are not yet present.
- The frontend has account-context checks in some async paths, but the Mini Cinema delayed sync path has mutable-session race exposure: delayed callbacks and row builders can read the active global session after scheduling. This is a hardening requirement, not evidence of a confirmed cross-account data leak.
- The repository contains migration-history ambiguity (duplicate `0005` version files and overlapping Storage policy names). The live migration ledger, live table definitions, grants, RLS and Storage policies have not yet been reconciled.

## Non-negotiable safety boundaries

1. Do not store media binaries, raw bucket paths, or signed URLs in `projects.settings`.
2. Do not treat a browser-supplied `owner_id` as authorization. Derive ownership from the authenticated server-side identity.
3. Do not expose service-role credentials to the browser.
4. Do not create public buckets or public asset URLs for private works.
5. Do not automatically transfer guest drafts or assets into a signed-in account.
6. Do not physically delete an asset while any project or other durable reference still uses it.
7. Do not apply migrations, alter live RLS/grants/policies, or deploy this integration until the live Supabase state has been inspected and reconciled.
8. Do not remove or rewrite existing localStorage project data as part of the first release.

## Target data model (subject to live-schema reconciliation)

Use a canonical asset record and a separate project-to-asset relationship.

- Asset record: stable asset ID, owner ID, media kind, lifecycle status, safe display metadata, storage object reference held server-side, created/updated timestamps, optional source asset/version relationship.
- Project relationship: project ID, asset ID, relationship role (for example cover, storyboard reference, soundtrack, voice track, generated image), ordering/slot metadata, created timestamp.
- Version/derivative relationship: derivative asset ID references its source asset ID; editing or exporting creates a new derivative record rather than overwriting the original.

These are logical contracts, not a decision to create particular SQL tables before inspecting the live schema. Reuse existing compatible tables only after verifying their actual columns, constraints, policies and ownership semantics.

## MVP user flow

### 1. Open Media Library

- Fetch only assets available to the authenticated owner through a server-authorized API.
- Show lifecycle states honestly: processing, ready, failed, quarantined, unavailable.
- Provide filters for All, Images, Video, Music & audio, Voice, Documents/scripts, Recent, Used in projects, Unused, Generated, Uploaded.
- Do not fabricate counts or sample assets.

### 2. Attach to a Mini Cinema project

- User opens a project and chooses “Добавить из медиатеки”.
- Show only ready assets the current owner is authorized to use and that are compatible with the selected project role.
- Attach the canonical asset ID through a server endpoint. Do not copy the binary and do not persist a client-provided storage path.
- Store only the relationship/reference in project state after the canonical relationship API is available.
- Re-check project ownership and asset ownership on the server in the same operation.

### 3. View and detach

- Project details show attached assets by role and safe display metadata.
- Detach removes only the project relationship; it does not delete the underlying asset.
- Asset detail shows the projects using it, subject to the owner's access rights.
- Before physical deletion, show the number and names of projects still referencing the asset. Require the user to detach it first or explicitly choose a safe detach workflow.
- Deleting a project must not delete a shared asset that is used elsewhere.

### 4. Guest workflow

- Guest assets and project drafts remain local to the current browser/device.
- Keep existing guest export behavior.
- If account import is introduced later, make it a clear user-initiated action with a preview and explicit confirmation. Never silently claim local guest data has been uploaded.

## Mini Cinema account-switch hardening

Before relying on project-to-asset attachment:

- Capture the initiating `userId` and `authContextVersion` when a sync is scheduled and when it starts.
- Pass the captured owner ID explicitly into row serialization and delete operations; do not read a mutable global session inside delayed callbacks.
- After every awaited network operation, verify the active user and context version still match before mutating UI, local account state, tombstones, or retry queues.
- Ensure an in-flight operation from account A cannot enqueue or apply state to account B after a session switch.
- Keep server-side RLS/authorization as the primary boundary; client guards are defense in depth.
- Add deterministic tests around switching accounts while a sync/select/upsert/delete is pending.

## API capability sequence

1. Read-only owner-scoped asset listing and asset detail.
2. Upload initiation/finalization with server-side validation, size/type limits, quarantine/processing states, and private storage.
3. Attach/detach project-asset relationship with server-side verification of both records.
4. Asset usage lookup and safe deletion workflow.
5. Derivative/version creation with source linkage.

Do not expose a generic bucket browser or accept arbitrary object paths from clients.

## Compatibility and rollback

- Existing `public.projects` rows and their `settings` payloads remain readable.
- Existing localStorage projects, guest drafts, tombstones and version histories remain intact.
- The first integration should be additive and feature-flagged.
- If the asset API is unavailable, Mini Cinema continues to work as it does today; the media attachment control reports that the library is unavailable rather than silently dropping references.
- Rollback disables the new attachment UI/API path without deleting asset records or changing existing project data.
- No backfill of old project content into the asset model is required for MVP.

## Test and release gates

### Automated

- Owner A can list and attach only A-owned assets.
- Owner B cannot list, read, attach, detach, or delete A-owned assets by guessing IDs.
- A cannot attach an asset to B's project; B cannot attach A's asset to B's project.
- Repeated attach requests are idempotent or return a clear conflict without duplicate relationships.
- Detaching a relationship does not delete the asset.
- Deleting one project leaves an asset intact when another project still references it.
- Asset deletion is blocked while references remain.
- Derivative records retain source linkage; original binary remains unchanged.
- Account switch during pending sync cannot mutate the new account's state.
- Guest drafts remain local and are not imported without an explicit user action.

### Manual / end-to-end

- Two disposable accounts, separate browser sessions/devices, and non-sensitive test media only.
- Verify refresh, sign-out/sign-in, account switching, and offline/reconnect behavior.
- Verify processing, failed, quarantined and unavailable states.
- Verify mobile layout and accessible touch targets.
- Confirm no media bytes or private signed URLs are placed in project JSON or browser logs.

### Release gate

Do not enable the feature in production until:
- Live migration ledger and actual schema are reconciled.
- Actual RLS, grants, Storage bucket privacy and Storage policies are inspected.
- Duplicate migration version and Storage policy overlap are resolved in a reviewed migration plan.
- Backend authorization tests and two-account end-to-end tests pass.
- Backup and rollback steps are documented.
- A separate production rollout approval is obtained.

## Out of scope for this milestone

- Public sharing/gallery/PULSE feed.
- Likes, comments, follows, messaging and notifications.
- Subscription, billing, credit deduction or paid generation.
- Automatic guest-to-account migration.
- Cross-user asset sharing or public asset links.
- Automatic migration of existing local project media.
