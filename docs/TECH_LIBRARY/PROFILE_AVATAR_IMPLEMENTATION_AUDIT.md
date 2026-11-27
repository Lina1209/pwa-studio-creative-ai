# Profile avatar implementation audit

**Date:** 27 November 2026  
**Branch:** `feature/character-library-foundation`  
**Status:** Nine local 2D SVG avatars and the profile picker are implemented in this feature branch. The additive database migration is draft-only and has not been applied to any live database. GitHub Actions run `46026736506` completed successfully on commit `8785f481124a1c0cd67027caa009ba1b18a4c041`; all three jobs passed: real-browser IndexedDB/account-switch checks, backend unit tests, and disposable PostgreSQL migration/integration tests. The run also verified migration `0021` defaults and constraints.

## Implemented

- Nine curated, locally hosted SVG avatars cover portrait, fantasy, animal, robot, cartoon, space, nature, and abstract categories.
- The optional `katty-assistant` portrait is included in both frontend catalog and backend allowlist. It does not replace or force a user's own avatar.
- Responsive picker in the account cabinet supports category filtering, preview, apply, and reset to the standard avatar.
- Guests persist selection under a dedicated browser-local key. Signed-in users persist through the authenticated `PATCH /api/community/profile` endpoint.
- Guest state is not sent to the profile API or reused as an authenticated user's selection.
- The resolved avatar is used consistently in account, top-bar, sidebar, and public community profile cards.
- Authenticated writes are fenced by user ID and auth-context version.
- Backend accepts only published catalog IDs and currently accepts only `2d`; explicit `3d` requests are rejected until real model assets and a renderer are supported.
- Public profile projections expose catalog ID and representation, not private storage paths.
- Migration `0021_profile_avatar_catalog.sql` is additive and tested only against disposable PostgreSQL in CI. It has not been applied to production.

## Verification

Latest branch workflow: [run 46026736506](https://github.com/Lina1209/pwa-studio-creative-ai/actions/runs/46026736506).

All three jobs completed successfully:
1. `character-backup-journal-browser-tests` — real-browser IndexedDB journal tests and frontend syntax/account-switch fencing.
2. `backend-unit-tests` — backend unit suite and cleanup race harness syntax.
3. `media-cleanup-postgres-integration` — disposable schema, feature migrations, avatar catalog defaults/constraints, idempotency, cleanup rollback, worker races, and stress harness.

This is feature-branch CI evidence only. It is not a production deployment or live Supabase verification.

## 3D status and safe next step

The repository currently has no package manifest, 3D model assets, glTF/GLB files, or identified 3D preview runtime. The 3D picker tab therefore remains disabled and explicitly marked as planned. A 2D image with lighting/shadows must never be represented as a real 3D model.

The implementation requirements are documented in `PROFILE_AVATAR_3D_ARCHITECTURE.md`. Real 3D support remains blocked on approved model assets, a reviewed renderer/runtime, mobile performance testing, and accessibility/fallback behavior. No provider or paid generation is selected.

## Explicit non-goals

No production schema changes, live Supabase calls, deployment, merge, provider selection, paid generation, custom upload, or active 3D rendering. Profile avatars remain separate from Character Library characters and film-project character snapshots.
