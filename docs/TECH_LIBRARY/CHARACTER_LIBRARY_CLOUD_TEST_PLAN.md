> **Status correction (2026-11-27):** This is a future disposable-project test plan, not evidence that cloud backup is currently available. The Character Library UI still stores cards in localStorage and image blobs in IndexedDB. It does not yet create or restore cloud character records. CL-02 and the statements below describing an implemented manual one-way backup are aspirational/outdated and must not be treated as executable steps until the frontend import/mapping flow is implemented. The new authenticated metadata API is in the feature branch; route and repository CI verification is in progress. Do not test against production or delete local data.

# Character Library cloud-backup test plan

This plan is for an isolated Supabase project only. Do not use the production project for the first run.

## Safety boundary
- Create a separate Supabase project named, for example, `PWA Studio Character Test`.
- Do not copy production user data into it.
- Configure the test frontend against the test project's public URL and publishable/anon key only in a disposable test deployment or local test copy.
- Never put a Supabase service-role key in frontend code, GitHub, browser storage, or screenshots.
- Do not merge this feature or run migration 0012 against production until the test matrix passes.

## Test setup
1. Create the disposable Supabase project.
2. Create two test Auth users, A and B, with separate email addresses controlled by the project owner.
3. Confirm the private `studio-media` bucket exists. Inspect SELECT, INSERT, UPDATE, and DELETE policies: all authenticated access must be scoped to the owner's first folder segment (`auth.uid()`), and no PUBLIC/anon read policy may expose this bucket.
4. Apply `supabase/migrations/0012_character_library_media_links.sql` in the test project's SQL Editor.
5. Run `supabase/tests/0012_character_library_preflight.sql`. It checks the private bucket plus owner-scoped SELECT/INSERT/UPDATE/DELETE policies and absence of PUBLIC/anon read policies. Investigate every FAIL before proceeding.
6. Deploy the feature branch to a disposable test frontend configured with the test project's public URL and publishable key. Do not change the production frontend configuration.

## Functional test matrix

| ID | Account | Action | Expected result |
|---|---|---|---|
| CL-01 | A | Create a character with one PNG/JPEG/WebP reference | Card and preview appear in A's browser library |
| CL-02 | A | Sign in and choose “Создать облачную копию” | Character row, media row, and object appear in the test project |
| CL-03 | A | Repeat cloud backup | No duplicate media rows or duplicate storage objects; stable cloud IDs are reused |
| CL-04 | B | Sign in and open the library | A's local cards are not displayed |
| CL-05 | B | Attempt a direct SELECT for A's character/media rows using B's authenticated session | No rows from A are returned |
| CL-06 | B | Attempt to insert a media row with A's character_id and B's owner_id | Composite foreign key rejects the cross-owner association |
| CL-07 | B | Attempt to read A's object in studio-media | Storage policy denies access |\n| CL-07a | B | Attempt to list A's folder and create an object under A's path | Both operations are denied |\n| CL-07b | B | Attempt to update or delete A's object | Both operations are denied |
| CL-08 | A | Back up a card with multiple references | Each object has path A/characters/<character UUID>/<reference ID> and each media row points to the same character and owner |
| CL-09 | A | Simulate a failed upload (e.g. temporarily disable test Storage INSERT policy) | UI reports failure; local card and image remain available |
| CL-10 | A | Switch from A to B and back | Local libraries remain isolated by account; no cross-account display |

## Evidence to record
- SQL preflight output (PASS/FAIL).
- Counts of test rows in characters and media_assets for A and B.
- Storage object paths (record paths only; do not share signed URLs or secrets).
- Screenshots of A's successful backup and B's empty/private view.
- Browser console errors, if any, with tokens and personal data removed.

## Pass criteria
- All SQL preflight checks pass.
- CL-01 through CL-10 pass.
- A can access A's records and objects; B cannot read, modify, or associate A's data.
- A repeated backup is idempotent.
- A failed backup never removes local data.

## Known limitations outside this test
- The feature currently remains local-first; cloud restore and backup UI are not yet implemented.
- Cloud restore, bidirectional sync, remote deletion/tombstones, conflict resolution, and automatic guest-to-account migration are not implemented.
- The 3D option is passport metadata only; it does not create a 3D model or animation.
