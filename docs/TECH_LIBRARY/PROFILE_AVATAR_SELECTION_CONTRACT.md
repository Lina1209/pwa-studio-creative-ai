# Profile Avatar Selection — product and technical contract

Status: planned feature; design contract only. This document does not add UI, database schema, generation providers, paid calls, or production changes.

## Goal

Every PWA Studio user should be able to choose a recognizable profile avatar. The selection must be welcoming and easy on a phone, with a useful standard collection first and a path from 2D artwork to 3D avatars.

A profile avatar represents the account in the profile, community, comments, creator cards, notifications, and other identity surfaces. It is distinct from the Character Library: profile identity and film/story characters are related concepts, but choosing a profile avatar must not automatically create a film character or expose private character-library content.

## Avatar catalogue

Provide a curated standard catalogue available without image-generation calls.

### 2D starter collection

Organize the standard 2D collection into browsable categories, for example:
- People and friendly portraits
- Fantasy and fairy-tale heroes
- Animals and cute creatures
- Robots, androids, and technology
- Cartoon and comic styles
- Space and science-fiction
- Nature, magic, and seasonal themes
- Minimal geometric symbols and abstract identities

Each catalogue entry should have a stable ID, display name, category, representation (2d), preview asset, accessibility label, and licence/source metadata. Category names and thumbnails should remain understandable on small mobile screens.

### 3D collection

Offer a separate 3D section with clearly labelled styles, such as:
- Stylized 3D characters
- Friendly 3D portraits
- Fantasy and adventure figures
- Cute 3D animals and creatures
- Robots and sci-fi figures
- 3D mascots and expressive characters

The UI must distinguish a real 3D asset/model from a 2D illustration that merely has a 3D-looking render style. Store representation and asset format explicitly; do not advertise a model as editable 3D unless a real 3D model is available.

## Selection experience

1. Show a default avatar immediately for new accounts; never require an upload or generation to complete profile setup.
2. Let every user open the avatar picker and browse categories.
3. Provide tabs or filters for 2D and 3D, category filtering, search, and a clear selected state.
4. Show a preview and confirm/apply action before replacing the current profile avatar.
5. Preserve the current avatar if loading or saving a replacement fails.
6. Allow the user to return to a standard default avatar at any time.
7. Keep the picker responsive and usable on Android/mobile, with large tap targets and accessible labels.
8. The standard catalogue must not be gated behind paid generation. Any future custom generation or premium asset policy must be explicit and must not remove the free standard choices.

## Custom avatar path

A future extension may allow a user to upload or create a custom avatar, subject to file validation, moderation, ownership checks, and storage quotas. Custom generation must be a separate explicit action; opening the picker or selecting a standard avatar must never trigger a paid provider call. Provider-neutral asset metadata should allow a later 3D pipeline without binding the product to one vendor.

## Identity continuity and Kitty

The PWA Studio assistant mascot Kitty (Katarina) must remain recognizable across 2D and 3D versions: the same core identity and distinguishing visual features, adapted to the representation rather than redesigned as unrelated characters. Kitty may appear as a curated mascot/assistant identity, but selecting Kitty as a profile avatar is optional and must not overwrite a user's choice.

## Data and ownership

A profile avatar selection should be represented by a stable catalogue ID or an owner-scoped custom asset reference, not by a client-supplied arbitrary storage path.

Suggested logical fields (not a migration):
- avatar_catalog_id — stable ID for a standard catalogue item, nullable for custom assets.
- avatar_representation — 2d or 3d.
- avatar_asset_id — nullable owner-scoped custom asset ID.
- avatar_updated_at — server-managed timestamp.

Server authorization must derive the owner from the authenticated session. A user may update only their own profile avatar. Public profile/community surfaces may expose only the approved avatar preview, never private storage paths, signed upload tokens, or unrelated character-library references. Guests may use a temporary local selection; it must not be mistaken for a registered account's persisted profile.

## Safety, privacy, and resilience

- Validate image/model formats, byte size, dimensions, and metadata on the server for custom uploads.
- Apply the platform's content-safety and reporting rules to custom public-facing avatars.
- Use private storage for custom originals; serve only an approved safe preview through the authorized media layer.
- Never trust a catalogue ID or custom asset ID without checking that it exists and is allowed for the requesting user.
- Do not expose one user's custom avatar asset to another user's private library.
- Keep the previous avatar until the new selection has been successfully saved and verified.
- Do not delete an old custom asset as part of the selection transaction; cleanup must use the existing fenced media lifecycle.
- Provide a graceful fallback if an avatar asset is unavailable.

## Acceptance criteria

- Every account has a visible default avatar and can open the picker.
- Standard 2D avatars are available across multiple categories without generation or payment.
- The picker includes a distinct 3D collection and accurately labels real 3D assets versus 2D artwork.
- Users can select, preview, apply, and restore a default avatar on mobile.
- Avatar selection persists across sessions and appears consistently in profile/community identity surfaces.
- One user cannot change, read, or delete another user's custom avatar.
- Selecting a profile avatar does not create, modify, or expose a Character Library character.
- Kitty retains one recognizable identity in both 2D and 3D variants.
- No paid generation, provider key, or production migration is required for the standard catalogue.

## Implementation order

1. Audit existing profile/community avatar fields and rendering surfaces in the feature branch.
2. Define a versioned, curated standard 2D catalogue and its category metadata.
3. Build and browser-test the mobile picker using standard assets only.
4. Connect selection to authenticated owner-scoped profile persistence and verify account-switch isolation.
5. Add 3D catalogue entries only when actual approved 3D assets and preview/render support are available.
6. Treat custom upload/generation as a separate later project with its own safety, quota, and lifecycle tests.

No profile avatar UI or schema is changed by this contract alone.
