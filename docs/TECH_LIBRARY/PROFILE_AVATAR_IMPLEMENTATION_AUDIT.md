# Profile avatar implementation audit

**Date:** 27 November 2026  
**Branch:** `feature/character-library-foundation`  
**Status:** initial 2D profile picker implemented in the feature branch; database migration is draft-only and not applied to any live database. GitHub Actions run `46026487046` completed successfully on commit `7340768af86ee856c157fab34d63cb16724696f7`: backend unit tests, frontend syntax/source-contract checks, profile-avatar migration verification, and PostgreSQL integration tests all passed.

## Existing profile model

The application already has a dedicated `public.user_profiles` table and authenticated community profile API:

- `user_profiles.user_id` is the primary key and references `auth.users(id)`.
- Existing profile fields are `username`, `display_name`, `bio`, `visibility`, `show_in_directory`, and nullable `avatar_path`.
- The backend derives the profile owner from the verified `StudioUser`; the client cannot choose another user's ID for an update.
- Own-profile reads and updates go through `/api/community/profile`.
- Public directory search and public profile reads return a deliberately limited field allowlist.
- Community cards currently render the first letter of the display name; profile settings do not expose an avatar picker.
- The account hero, sidebar profile, and top-bar avatar are also currently initials/placeholders.

## Important compatibility finding

Do not add a second parallel avatar URL or profile table. The existing nullable `avatar_path` is an established field, but it represents a storage path and must not be overloaded with arbitrary catalog IDs or client-provided URLs.

The new catalog selection should use explicit logical fields, separate from `avatar_path`:

- `avatar_catalog_id`: stable ID from the curated, versioned catalog.
- `avatar_representation`: `2d` or `3d`.
- `avatar_asset_id`: optional future owner-scoped custom asset reference; not active.
- `avatar_updated_at`: timestamp.

A future additive migration must preserve existing `avatar_path` values and set safe defaults for existing accounts. API validation must accept only published catalog IDs and must derive the owner from authentication. Public profile responses may expose only the catalog ID and representation, never storage internals.

## UI integration surfaces

1. Personal cabinet profile hero: primary avatar preview and selection entry point.
2. Community profile form: avatar preview and picker controls; no duplicate avatar editor.
3. Community search cards and public profile: render the selected catalog avatar with a safe fallback.
4. Sidebar and top-bar: use the same resolved profile avatar, not separately persisted copies.
5. Guest: use a guest-only default avatar; never reuse the previous signed-in user's selected avatar.
6. Account switching: fence async avatar loads and saves by authenticated user ID and auth-context version, matching the existing Character Library account-switch protections.

## Asset and representation status

The repository currently contains only the generic app icon as a standalone image asset; there is no approved curated portrait/avatar collection and no real 3D model catalog or 3D preview runtime.

Therefore:
- Do not label emoji, initials, or a 2D illustration with a 3D-looking effect as a real 3D avatar.
- Build and validate the catalog contract and 2D assets first.
- The 3D tab must remain clearly marked as planned/unavailable until actual approved 3D assets and a supported preview/render path exist.
- Standard catalog avatars should be free and local/static; no image-generation calls or paid provider calls are implied.
- Custom upload and generated avatars remain future, separately consented features.

## Implemented in the feature branch

- Additive migration `0021_profile_avatar_catalog.sql` introduces `avatar_catalog_id`, `avatar_representation`, and `avatar_updated_at`; it has not been applied to production.
- Backend allowlist currently accepts eight published static 2D IDs, derives the owner from the authenticated session, and rejects unknown IDs or 3D selection until real 3D assets exist.
- Nine locally hosted SVG portraits cover people, fantasy, animals, robots, cartoon, space, nature, and abstract categories; the optional Katty mascot portrait is included without replacing a user's own selection.
- The account cabinet has a responsive category filter, 2D collection, preview, apply, and reset-to-standard controls for both guests and signed-in users.
- Guest selection is stored under a dedicated browser-local key and is never sent to the profile API or reused as an authenticated user's choice.
- Community search cards and public profile cards render the selected catalog portrait; the account hero, top navigation, and sidebar use the same resolved avatar.
- Public profile projections expose only catalog ID and representation, not private `avatar_path` storage paths.
- Selection requests are fenced by authenticated user ID and auth-context version.
- Backend, SQL migration, and frontend source-contract tests were added; latest CI result is pending.

## Remaining safe implementation sequence

1. Verify the new backend, SQL, and frontend contract tests in GitHub Actions; fix failures before proceeding.
2. Add the same catalog to any additional account/profile surfaces discovered in the UI audit, without duplicating persisted state.
3. Add guest-only local selection if guest profile UI is exposed; never reuse a signed-in user's choice.
4. Render the same resolved avatar in sidebar/top bar if those surfaces have a stable profile component.
5. Add real 3D support only after approved model assets and a real preview runtime are available.

## Explicit non-goals

No production schema changes, no live Supabase calls, no deployment, no provider selection, no paid generation, no custom upload, and no 3D placeholder presented as a real 3D model.
