# Character Library → Mini Movie Studio integration contract

Status: design contract only. No production schema or Mini Movie Studio workflow is changed by this document.

## Goal
A creator should define a character or location once in the Character Library and reuse it across projects. The studio must preserve identity and visual continuity without copying large image blobs into every project.

## Source of truth
- The character passport is the canonical source for name, description, type, 2D/3D representation intent, voice notes, face/profile, silhouette, wardrobe/accessories, palette and emotional range.
- Reference images remain owned by the library record and its media assets. A project link points to the character ID; it does not duplicate the original files.
- A project may use a character without changing the master passport.
- Editing the master passport must not silently rewrite an already approved film. Projects should store a small immutable snapshot of the passport fields used at the time of approval.

## Future relational model (proposal only)
The current schema already has `characters(id, owner_id, ...)`, `projects(id, owner_id, ...)` and `media_assets(character_id, owner_id, ...)`.

Before implementing project reuse, add a dedicated join table rather than putting arbitrary character IDs into project JSON:

```sql
-- Proposal only; do not run this snippet.
create table public.project_character_links (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null,
  character_id uuid not null,
  role text not null default 'cast',
  passport_snapshot jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (project_id, character_id, role),
  foreign key (project_id, owner_id)
    references public.projects(id, owner_id) on delete cascade,
  foreign key (character_id, owner_id)
    references public.characters(id, owner_id) on delete restrict
);
```

Prerequisite: confirm that `projects` has a unique constraint on `(id, owner_id)`. If not, add it in a separately reviewed migration. Enable RLS and use owner-only `USING` and `WITH CHECK` predicates. Never rely on a client-supplied owner_id without RLS enforcement.

## Mini Movie Studio workflow
1. **Implemented in the feature branch (local MVP):** the “Персонажи из вашей библиотеки” picker appears in the cast/locations stage. It reads only the active browser scope (signed-in user ID or guest), supports selecting multiple cards, and inserts their passport text into the cast description.
2. **Implemented locally:** the picker uses the existing owner-scoped local library key. Guest mode sees only the current browser's guest library.
3. **Partially implemented:** the creator can select cards and save passport snapshots (identity, description, representation, voice, face, silhouette, wardrobe, palette, and reference IDs/names) with the project. The creator can explicitly select which library references belong to a character and assign that character to scene numbers (for example 1, 2, 4). Reference image blobs are not copied or attached to the project yet.
4. **Implemented locally:** a project stores `characterLibrarySnapshots` with the master local card ID, selected reference IDs, scene number assignments, and a copied passport snapshot. The storyboard stage displays selected reference names and their assigned scene numbers as author guidance. The snapshot is independent of later master-card edits. This is a browser-local reference, not a cloud foreign-key relationship.
5. Future: let the creator explicitly choose “Обновить паспорт из библиотеки” if the master record changes. Show a before/after summary; never silently replace an approved snapshot.
6. Build generation prompts from the approved snapshot plus selected references and the current scene action. Keep scene action separate from immutable identity traits.
7. Save the project link and snapshot with the project version history so restoring a project restores its cast/visual continuity.

## Continuity prompt structure
The prompt builder should keep these sections separate:
- **Identity lock:** face, hair, eye color, body/silhouette, distinguishing marks.
- **Wardrobe lock:** clothing, accessories and allowed variations.
- **Palette and style:** color palette, rendering style, 2D/3D intent.
- **Voice profile:** voice notes only when audio generation is requested.
- **Scene action:** pose, expression, movement, camera, lighting and environment for this shot.

The model may vary scene action, pose and camera, but should not reinterpret identity-lock fields unless the creator explicitly asks for a redesign.

## Security and privacy
- Never expose another user's character list or reference object paths.
- Do not make the storage bucket public.
- Do not store signed URLs as permanent references; store stable storage paths and request short-lived signed URLs when a UI preview needs them.
- Keep all owner checks server-side/RLS-enforced. Client-side filtering is only a UI convenience.
- A project link must not grant cross-owner access to a character or media object.
- Character deletion should be blocked while project links exist, or require an explicit “unlink from projects” flow that preserves approved snapshots. Do not cascade-delete approved project snapshots.

## Acceptance criteria for future implementation
- A creator can add a library character to a project without re-uploading the original image files.
- The same character can be reused in multiple projects.
- Each project version retains its approved passport snapshot.
- Updating the library master does not silently change existing projects.
- A user cannot link, read or attach another user's character or image.
- Guest and authenticated libraries remain separate unless a deliberate, confirmed migration flow is implemented.

## Not implemented yet
The local picker and passport snapshot are implemented in the feature branch only. The following are still not implemented: database join table, cloud relationship and cross-device loading, attaching actual reference image blobs to a project/scene, signed preview URLs, actual image upload to a video/image generation provider, automatic prompt assembly/enforcement across generation routes, explicit passport refresh with diff, cloud restore, and bidirectional sync. Scene number assignments currently provide storyboard author guidance only; they do not yet trigger rendering or pass image files to a model. The picker has not passed browser E2E or Supabase integration tests. The proposed SQL remains design-only and must not be run until separately reviewed and tested.

## 9. Private reference-upload API status (2026-11-27)

The authenticated server endpoint `POST /api/characters/{character_id}/references` is implemented as a server-only upload path. It requires an authenticated owner and an existing owner-matched row in `public.characters`; it validates the image bytes and MIME type, caps the body at 8 MiB, derives immutable object identifiers and the Storage path on the server, reserves the `media_assets` row plus verification outbox event atomically, uploads with the server-only Storage credential, and leaves readiness to the independent verification worker. The browser cannot choose the bucket or object path.

The local Character Library currently does **not** create or load `public.characters` rows. It stores passport metadata in owner-scoped localStorage and image blobs in IndexedDB. Therefore the upload endpoint is not yet callable from the current library UI: a local character UUID is not proof that a corresponding server character row exists. Do not wire the upload button directly to this endpoint until authenticated character create/read/update/list APIs and an explicit local-to-cloud mapping/sync design are implemented and tested.

Failure behavior:
- A failure before reservation creates no object and no media row.
- A failure after reservation leaves a durable pending reservation and verification outbox event; the verifier can reconcile an object that reached Storage despite a lost HTTP response.
- A duplicate-object response is not treated as proof of success. The worker must independently verify the exact reserved object and fingerprint before marking the asset ready.
- Repeated requests use the same idempotency key and deterministic server-derived IDs; changed bytes under the same key must conflict rather than overwrite.
- Local IndexedDB images remain the source of truth until explicit cloud backup succeeds. No local image is deleted by a cloud upload attempt.

Migration 0019 draft removes authenticated direct INSERT/UPDATE/DELETE access to `studio-media`; only owner-scoped export uploads remain available directly to browser clients. The private character upload endpoint uses the server credential after reservation. This migration remains draft-only and has not been applied to any live database.


## 10. Authenticated character passport API foundation (2026-11-27)

The feature branch now contains a server-side repository and authenticated routes for listing, creating, reading, and patching character passport metadata. Routes are registered under the configured API prefix:
- `GET /characters`
- `POST /characters`
- `GET /characters/{character_id}`
- `PATCH /characters/{character_id}`

Every route requires `get_current_user`. The server derives owner_id exclusively from the verified session subject. List/read/update PostgREST requests are owner-filtered; missing and foreign records return the same 404. Request schemas reject unknown fields such as owner_id and storage_path. The API excludes avatar_url and private media paths from its response contract, bounds passport JSON to 24 KiB, and exposes no delete operation. Character deletion remains behind the fenced cleanup lifecycle.

This is an API foundation, not cloud-library activation. The frontend remains local-only; do not change IndexedDB/localStorage behavior or add UI calls yet. Before UI integration, verify the new routes and repository tests in CI, run disposable Supabase A/B account tests, and define an idempotent local-to-cloud mapping/import flow with a non-destructive backup. No production migration, deploy, merge, or live database operation is authorized.


## 10. Per-reference cloud backup status API (feature branch)

The authenticated `GET /api/characters/{character_id}/references` endpoint returns the owner’s media records for that character, including each asset’s verification lifecycle state (`pending_upload`, `object_uploaded`, `ready`, `upload_failed`, `cleanup_pending`, or `deleted`) and safe file metadata. The query is filtered by owner, character, and private `studio-media` bucket. The response excludes storage paths, bucket names, internal metadata, owner IDs, and signed URLs, and is marked `private, no-store`.

This gives a future importer a per-image progress/read-back checkpoint. An image is backed up only when its independently verified database status is `ready` and its asset ID is matched to the local reference’s persisted upload mapping. `object_uploaded` is not proof of successful backup. A ready asset can additionally be fetched through the existing authenticated `/api/media/{asset_id}/content` proxy, which rechecks ownership/readiness and validates downloaded image bytes. No local IndexedDB blob may be removed based only on the upload response or status-list result.


## 11. Canonical visual identity references (2026-11-27)

The feature branch now includes a versioned, machine-readable Katty/Katarina visual identity manifest at `assets/characters/katty/identity.v1.json`. Its stable key is `katty-katarina`; the profile avatar catalogue entry `katty-assistant` points to that manifest. The manifest records identity-lock traits (face, green eyes, freckles, curly red hair), wardrobe and accessories, palette, allowed expressions/poses, prohibited identity drift, and separate 2D/3D readiness states.

This key is a visual continuity reference only. It is not a user ID, character row ID, owner identifier, or automatic relationship between a profile avatar and a Character Library card. A creator must explicitly choose to use the Katty identity in a future Character Library workflow.

When a Character Library card or project snapshot later adopts a canonical identity:
- store the stable identity key and manifest version alongside a copy of the resolved visual identity fields;
- keep any creator-specific additions and permitted variations separate from the canonical identity lock;
- freeze the resolved identity data in each approved project snapshot;
- never silently update an approved project when the master manifest changes;
- keep the profile avatar optional and independent from the creator's selected cast.

The current manifest marks 2D as implemented and 3D as `not_created`. It does not provide a model file, invoke generation, load a renderer, or authorize any external service. A future 3D model must be reviewed against the same identity lock and have an accessible 2D fallback.
