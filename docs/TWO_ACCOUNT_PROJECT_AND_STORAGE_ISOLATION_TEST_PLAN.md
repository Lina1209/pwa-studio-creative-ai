# Two-account project and Storage isolation test plan

Status: **test plan only**. No live database, account, Storage object, or production setting is changed by this document.

## Purpose

Verify that PWA Studio keeps project records and future media assets isolated between two authenticated users, while preserving guest-local drafts and the existing Mini Cinema project workflow.

This plan is intentionally separate from the read-only SQL inventory in `supabase/diagnostics/inspect_project_asset_security.sql`. SQL metadata and policy listings are necessary evidence, but they do not prove runtime isolation.

## Safety prerequisites

- Use two disposable test accounts (Account A and Account B), not the owner's everyday account.
- Use a non-production Supabase project whenever possible. If only production is available, stop before creating, uploading, deleting, or modifying anything until a separate production test approval and cleanup plan exist.
- Confirm the actual schema, migration ledger, RLS policies, grants, and Storage buckets first.
- Use harmless synthetic project names and tiny non-sensitive test files.
- Never place service-role keys, passwords, bearer tokens, signed URLs, private media, or real user content in test notes.
- Do not apply migrations or alter policies as part of this test.

## Test matrix

| ID | Scenario | Account / action | Expected result |
|---|---|---|---|
| P-01 | Create project | A creates a Mini Cinema project | Project is saved under A's authenticated owner ID; it appears in A's list. |
| P-02 | Isolated listing | B opens Mini Cinema | A's project is absent from B's cloud list. |
| P-03 | Direct read denial | B attempts to read A's project by its UUID through the normal authenticated client path | No project data is returned; access is denied or appears not found. |
| P-04 | Direct update denial | B attempts to update A's project UUID | No row is changed; A's title/settings remain unchanged. |
| P-05 | Direct delete denial | B attempts to delete A's project UUID | No row is deleted; A can still open it. |
| P-06 | Owner update | A edits and saves A's project | Changes appear for A and persist after reload. |
| P-07 | Cross-device read | A signs in on a second clean browser/device | A's cloud-synced project appears, subject to the current app's supported sync behavior. |
| P-08 | Guest isolation | Guest creates a local draft, then signs in as A | Guest draft is not silently assigned to A unless an explicit, reviewed import flow exists. |
| P-09 | Account switch | A signs out and B signs in in the same browser while sync is pending | No A project is displayed or written into B's local/cloud state; no stale A UI update occurs. |
| P-10 | Storage visibility | A uploads a synthetic test object to a private test bucket, if upload support exists | A can access it only through the intended authenticated path; it is not anonymously public. |
| P-11 | Storage cross-account denial | B attempts to list, read, overwrite, or delete A's test object | Every unauthorized operation is denied; A's object remains unchanged. |
| P-12 | Lifecycle cleanup | A deletes the synthetic test object using the supported flow | Object and metadata reach the documented deleted state; no orphaned accessible object remains. |

## Evidence to record

For each test, record only:
- test ID and UTC timestamp;
- disposable account label (A or B), never email or credentials;
- operation and pass/fail;
- HTTP status or safe error code;
- whether the source record/object remained unchanged;
- sanitized request/correlation ID, if available.

Do not record bearer tokens, cookies, signed URLs, object contents, prompts, or private user data.

## Pass criteria

- All P-01 through P-09 pass before declaring current project cloud sync account isolation verified.
- P-10 through P-12 are marked **not applicable / not implemented** if there is no end-to-end media upload and asset API yet. Do not treat a configured bucket alone as proof of a working asset library.
- Any cross-account read, write, list, overwrite, or delete is an immediate security failure. Stop testing, preserve safe evidence, and investigate before release.
- Account-switch races must be tested with delayed network responses and pending sync callbacks, not only with a quick sign-out/sign-in.
- Repeat the critical denial tests after any RLS, Storage policy, auth, sync, or asset-service change.

## Current implementation boundary

The current Mini Cinema source has a cloud project-record sync path using `public.projects`; project settings/records are not the same thing as media binary storage. Guest drafts are device-local. A shared cross-studio asset API, upload intent/completion flow, owner-scoped asset listing, and short-lived download authorization have not been verified as implemented.

Therefore, do not mark Storage tests as passed merely because a Storage bucket exists. First verify the live bucket configuration and policies, then implement the server-side asset lifecycle and run these tests in a disposable environment.

## Release gate

This plan does not authorize production SQL, migrations, policy changes, bucket changes, account creation, uploads, or deployment. Those require a separately reviewed implementation and an explicit release decision.
