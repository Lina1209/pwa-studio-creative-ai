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
1. Add an explicit “Выбрать из библиотеки” action in the cast/locations stage.
2. Show only the signed-in user's characters and scenes. Guest mode sees only the current browser's guest library.
3. Let the creator select a character, then choose which reference images to attach to this project/scene.
4. Store a passport snapshot when the creator confirms the selection. Keep a link to the master character ID for future manual refresh.
5. Let the creator explicitly choose “Обновить паспорт из библиотеки” if the master record changes. Show a before/after summary; never silently replace an approved snapshot.
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
This file is an architectural contract only. It does not add the join table, project picker UI, prompt injection, cloud restore, or bidirectional sync. Those require separate implementation and tests.
