# PWA Studio — Creative Control Center

Status: implementation specification for the next shared-workspace increment. This document defines the control center as the coordination layer over existing studios; it does not claim that every card, live job feed, or cross-branch automation is already implemented.

## Purpose

The Creative Control Center is the user's starting point and return point. It answers four questions without making the user understand the internal architecture:

1. What am I working on?
2. What is happening now?
3. Where are my finished and reusable materials?
4. What is the most useful next action?

It is not a second editor and must not duplicate the detailed interfaces of the individual studios. It is the shared dashboard and navigation layer for the creative tree.

## Current verified foundation

The repository currently has:
- a home view and sidebar navigation in the single-page frontend;
- account sign-in/sign-up/reset UI and Supabase Auth client integration;
- a Mini Movie Studio with local-first project drafts, editing, copying, deletion confirmation, and local version history;
- AI Companion conversation history backed by Supabase;
- Prompt Studio UI and authenticated backend prompt endpoint;
- navigation areas for video creation/editor, media library, voice/music, scenes, guide, rules, account, and settings.

Important boundaries:
- Cloud project persistence has a migration and source implementation, and the implementation roadmap records a live table/bucket and test-row verification; cross-device behavior and conflict/deletion cases still need end-to-end checks.
- Media upload UI is not implemented.
- Video/image/music/voice generation providers, timeline rendering, and MP4 export are not connected.
- Audio Studio currently supports local microphone/file preview, not upload or generation.
- Do not show invented live job counts, generated asset counts, cloud status, provider status, or balances.

## Control Center information architecture

### A. Welcome and quick creation

A concise greeting and a primary action area:
- Continue a recent project.
- Start a project.
- Open Prompt Studio.
- Ask AI Companion.
- Enter a studio directly.

Quick actions should be outcome-oriented ("Start a film", "Prepare a prompt", "Work with audio"), not operation-code-oriented.

### B. My projects

A compact project list or card grid:
- project title;
- project type / creative intent;
- last edited timestamp;
- local/cloud persistence indicator with truthful state;
- draft / in progress / ready label;
- Continue action;
- context menu for rename, duplicate, and delete where those actions are actually supported.

Initial source of truth:
- existing Mini Movie Studio project records;
- local drafts remain available when cloud sync is unavailable;
- future project types may use the same project shell and metadata contract.

Do not show "cloud saved" merely because the user is signed in. Show it only after a successful server acknowledgement for that specific version. If local-only, say "Saved on this device". If a sync attempt fails, preserve the local draft and explain the status.

### C. Activity and task center

A unified activity stream is a future shared service, not a client-side guess. It should eventually include:
- queued / running / waiting / completed / failed / cancelled jobs;
- the studio and project that own each task;
- start/update timestamps;
- a safe progress indicator only when the provider reports meaningful progress;
- retry or resume actions only when the backend says they are valid;
- links to the resulting asset or project.

For the first increment, show only truthful local activity such as recently edited projects and recent assistant conversations. Do not fabricate asynchronous jobs while generation integrations are absent.

### D. Recent creations and asset shelf

A reusable shelf for outputs:
- thumbnails and media type;
- title and creation date;
- source project;
- open / reuse / download actions only when the underlying asset exists and the action is implemented.

Until Media Library upload and metadata APIs are complete, this area should be an honest empty state with guidance, or show only verified local project artifacts. Do not imply that remote assets are stored.

### E. Studio launcher — branches of the tree

Group the studio entry points by creative outcome:
- Film & Video: Create Video, Mini Movie Studio, Video Editor, Script & Scenes.
- Images: Image Studio (planned until its provider and workflow are implemented).
- Sound: Voice & Music / Audio Studio (local preview exists; cloud generation is not connected).
- Intelligence: AI Companion and Prompt Studio.
- Library: Media Library (upload UI pending).

Each card has a short description, readiness badge, and opens the corresponding existing view when one exists. Planned branches should be marked "Coming next" or "In development", never presented as active generation tools.

### F. Workspace health and account

Keep operational information compact:
- signed-in account;
- current workspace / project context;
- backend connection only if actively checked;
- privacy and safety guidance;
- settings and sign-out.

Never expose secrets, internal provider credentials, raw moderation data, or other users' records.

## Shared data contract

The control center should consume normalized view models rather than reading each studio's DOM or inventing state.

### Project card

- `project_id`
- `owner_id` (server-derived; never trusted from browser input)
- `title`
- `project_type`
- `status` (`draft`, `in_progress`, `ready`, `archived`)
- `persistence_state` (`local_only`, `sync_pending`, `synced`, `sync_error`)
- `updated_at`
- `last_opened_at`
- `thumbnail_asset_id` (nullable)
- `current_version` (nullable)

### Activity item

- `activity_id`
- `owner_id`
- `project_id` (nullable)
- `branch`
- `operation_code` (nullable for non-AI/local actions)
- `logical_operation_id` (nullable)
- `status`
- `created_at`
- `updated_at`
- `safe_progress` (nullable; only if provider supplies meaningful progress)
- `result_asset_id` (nullable)
- `user_safe_message`

The activity model should align with `PWA_STUDIO_OPERATION_REGISTRY.md` and the unified resource measurement envelope. A task attempt must not appear as a second user-facing project or double-count as a second logical operation.

### Asset card

- `asset_id`
- `owner_id`
- `project_id` (nullable)
- `media_type`
- `title`
- `storage_state`
- `created_at`
- `preview_reference` (short-lived signed URL or local object URL, never a public bucket URL by default)
- `source_operation_id` (nullable)

These are interface contracts for implementation planning, not a claim that corresponding database tables or endpoints already exist.

## Interaction rules

- Selecting a project opens the correct studio and restores its context.
- Creating from a quick action either creates a project draft or clearly explains why sign-in / a dependency is required.
- A failed cloud save never discards a local draft.
- Switching accounts clears user-specific UI state before loading the next account's projects and activity.
- Every list is owner-scoped server-side; hiding another user's records in the browser is not security.
- Empty states explain what is available now and what is coming, with no fake sample data presented as real user content.
- Destructive actions require confirmation and must preserve a recoverable path where supported.
- Keyboard, screen-reader, mobile, light-theme, and dark-theme behavior must be included in acceptance tests.

## Delivery plan

### Increment 1 — truthful dashboard composition
1. Reuse the existing home view and sidebar rather than introducing a competing navigation system.
2. Add clear sections for quick creation, recent projects, studio launcher, and recent local activity.
3. Source project cards from the existing Mini Movie Studio local/cloud project layer; display persistence state from actual save acknowledgements.
4. Add readiness labels to branches whose providers are not connected.
5. Verify account switching does not leak previous-account project cards.

### Increment 2 — unified activity
1. Define backend-owned task/job read API and owner authorization.
2. Persist lifecycle transitions and idempotent operation identifiers.
3. Connect each studio adapter to the shared activity contract.
4. Add polling or push updates only after lifecycle persistence is reliable.
5. Add cancellation/retry semantics and reconcile ambiguous provider outcomes.

### Increment 3 — asset shelf

**Presentation foundation:** the Creative Control Center now has an explicitly empty asset-shelf panel with links to Media Library and neutral type labels for images, video, audio/music, and projects. This is navigation and expectation-setting only; it does not claim that assets exist or that upload/storage is implemented.

Remaining implementation gates:
1. Finish private media upload/list/delete UI.
2. Add owner-scoped asset metadata and signed preview URLs.
3. Link generated outputs to their source project and operation.
4. Add reuse/download actions with server-side authorization.
5. Replace the honest empty state only with assets returned by the verified storage/metadata layer.

### Increment 4 — cross-studio orchestration
1. Introduce parent creative workflows composed of registered child operations.
2. Keep prompts, project versions, scene references, and asset relationships linked.
3. Present user approval gates before external provider calls, publication, sharing, or future charges.
4. Add end-to-end tests across project → generation → asset → editor → export when those providers and services exist.

## Acceptance criteria

The first increment is complete only when:
- the dashboard shows actual projects, not mock cards;
- local-only and cloud-synced states are distinguishable and accurate;
- a project card opens the correct existing workflow;
- account switching clears prior-account content;
- planned integrations are visibly labelled as planned;
- no fake task progress, generated outputs, asset counts, or credit balances appear;
- the layout works on a narrow Android screen and in both themes;
- all existing project drafts and studio routes continue to work.

## Safety and rollout boundary

- No new database migration is implied by this specification.
- Do not enable credit deductions, paid operations, or provider calls as part of dashboard presentation work.
- Do not deploy or merge a UI implementation without checking the PR diff and relevant CI.
- Verify live schema and policies before adding new persistence tables.
- Treat user media as private by default; use signed access and owner checks.
- Keep the distinction between local drafts, cloud-persisted projects, provider jobs, and final assets visible to the user.

## Related documents

- `PWA_STUDIO_CAPABILITY_CATALOG.md`
- `PWA_STUDIO_OPERATION_REGISTRY.md`
- `UNIFIED_RESOURCE_MEASUREMENT_MAP.md`
- `IMPLEMENTATION_ROADMAP.md`
