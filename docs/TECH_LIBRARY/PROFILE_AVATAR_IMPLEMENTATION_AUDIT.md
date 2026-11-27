# Profile avatar implementation audit

**Date:** 27 November 2026  
**Branch:** `feature/character-library-foundation`  
**Status:** source audit completed; implementation not yet activated.

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

## Next safe implementation sequence

1. Add an additive profile-avatar catalog migration and backend allowlist validation, with tests; do not execute it against production.
2. Add a small curated static 2D catalog with stable IDs, descriptive labels, and accessible alternatives.
3. Add a mobile-friendly picker to the existing profile surfaces, with preview/apply/reset and a fallback.
4. Render the selected avatar consistently in account, community cards, sidebar, and top bar.
5. Add browser tests for guest separation, account switching, invalid catalog IDs, and persistence/readback.
6. Add real 3D support only after approved model assets and a real preview runtime are available.

## Explicit non-goals

No production schema changes, no live Supabase calls, no deployment, no provider selection, no paid generation, no custom upload, and no 3D placeholder presented as a real 3D model.
