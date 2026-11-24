# Media Library — Storage Isolation and Rollout Checklist

Status: source-level audit and implementation plan. This document does not claim that live Supabase settings were inspected or changed.

## 1. Verified source facts

- Mini Cinema project records are stored in `public.projects`; the browser query is explicitly filtered by the captured `owner_id` and `project_type = movie`. Supabase RLS is expected to provide a second boundary.
- Mini Cinema local drafts use a per-account key: `pwa-studio-movie-projects:<user UUID>`; guest drafts use a separate `guest` key. Deletion queues are likewise per account.
- The cloud-operation controller captures an owner/auth-generation context and rejects stale operations after account switch or reauthentication. The production-shared controller has deterministic tests for delayed SELECT, upsert, delete, pending work, guest behavior and owner filtering.
- Backend asset schemas and owner-scope helpers exist, but are not connected to API routes. There is no implemented asset metadata table/API, upload-intent endpoint, upload completion verification, signed access endpoint, project-asset relationship persistence, or safe deletion worker.
- Source migrations define private `studio-media` and `studio-exports` buckets. Their policy definitions conflict: migration 0002 covers both buckets, while migration 0005_cloud_projects_and_storage recreates identically named policies for `studio-media` only. There are two distinct files with version prefix `0005`.

## 2. Data ownership model

The target ownership chain is:

`verified auth principal -> owner-scoped project -> owner-scoped asset -> owner-scoped project_asset relationship -> private storage object`

Rules:

1. Derive owner UUID only from the verified backend auth principal. Never accept it from request JSON, query parameters, project settings, object key, or browser localStorage.
2. For service-role REST calls, explicitly filter every table query and mutation by owner. Service-role credentials bypass ordinary user RLS and therefore do not replace explicit authorization.
3. Verify both sides of every relationship: the asset belongs to the authenticated owner and the project belongs to the same owner.
4. Use server-generated opaque object keys under a per-owner prefix. Do not allow client-provided bucket names or paths.
5. Keep buckets private. Return only short-lived, narrowly scoped access URLs after authorization; never persist signed URLs in project JSON or asset metadata.
6. Guest drafts remain local until the user explicitly imports them after signing in. Never silently merge guest data into an account.

## 3. Canonical asset lifecycle

Recommended lifecycle:

`upload_intent -> uploaded_pending_verification -> processing/quarantined -> ready -> deleting -> deleted`

Failure paths include `failed`, `expired`, and `unavailable`.

- Validate declared media kind, filename, size and MIME allowlist at upload-intent time.
- Treat client-declared MIME/size as hints only. Verify actual object size and content type server-side after upload; add checksum verification where practical.
- Do not make an asset reusable until verification succeeds.
- Use idempotency keys for intent creation and completion retries.
- Enforce per-file limits, per-owner storage quotas, concurrency limits and request rate limits before issuing upload authorization.
- Keep original assets immutable. Crops, transcodes, mixes, edited images and exports become derivative assets with a source-asset reference.
- Remove a project link without deleting the shared original. Before deleting an asset, inspect active project/job references; use a retryable cleanup worker and do not report physical deletion until Storage confirms it.

## 4. Required metadata and relationship invariants

Canonical asset metadata should include: immutable UUID, owner UUID, bucket, server-generated object key, media kind, verified MIME, verified byte size, checksum where available, safe display name, lifecycle status, source/derivative reference, dimensions/duration when known, timestamps, and retention/deletion state.

Project-asset relationship should include: UUID, owner UUID, project UUID, asset UUID, role, optional slot, position, and timestamps.

Database constraints and authorization must ensure:
- asset owner and project owner equal relationship owner;
- relationship uniqueness is defined for the intended role/slot/position;
- deleting a project does not cascade-delete a shared asset;
- deleting an asset is blocked or deferred while active references/jobs exist;
- no cross-owner relationship can be created even if a caller guesses another UUID.

Do not finalize SQL types, foreign keys, uniqueness, triggers or migration version until the live schema and migration ledger are reconciled.

## 5. Read-only live audit required before implementation

Use the existing `supabase/diagnostics/inspect_project_asset_security.sql` as a starting point. It inspects migration-ledger locations/columns, relevant table columns and constraints, indexes, RLS flags, policies, grants, bucket settings and approximate row counts. It is SELECT-only.

The live audit must record, without exposing user content:
- migration ledger entries and how the two historical 0005 files were actually handled;
- exact `public.projects` column nullability, foreign keys, constraints, indexes, grants and RLS policies;
- whether `studio-media` and `studio-exports` exist, are private, and have expected limits/MIME allowlists;
- every Storage.objects policy, including command, role, USING and WITH CHECK expressions;
- relevant bucket/object ownership and policy behavior using two dedicated test accounts and harmless test files;
- whether service-role storage operations are explicitly owner-checked by backend code.

Do not export object names, user filenames, prompts, signed URLs, access tokens, credentials or private media into audit notes. Record aggregate outcomes only.

## 6. Two-account integration test matrix

Use two dedicated non-production test accounts A and B and harmless synthetic files. For every case, assert both API result and resulting database/storage state.

| Scenario | Account A | Account B | Expected result |
|---|---|---|---|
| List assets | List own assets | List own assets | Each sees only its own records |
| Download | Request own asset | Request A asset by guessed UUID | A succeeds; B receives non-enumerating denial |
| Upload path | Upload to server-issued path | Attempt to substitute A owner/path | B cannot write into A namespace |
| Attach | Attach own asset to own project | Attach A asset to B project | A succeeds; cross-owner attach denied |
| Relationship | Reuse one asset in two A projects | Attempt reuse in B project | Same-owner reuse works; cross-owner reuse denied |
| Delete link | Remove one A project link | Read remaining A reference | Asset remains available while another reference exists |
| Delete asset | Request deletion while referenced | Request A asset deletion | Deletion is blocked/deferred; B cannot affect A |
| Signed access | Obtain short-lived A URL | Attempt access to A object | URL expires; B cannot mint or reuse access |
| Session switch | Delay A request, sign in as B | Complete old A request | Old response cannot overwrite B local/UI state |
| Guest import | Create guest draft | Sign into A explicitly | Only explicit import transfers draft |

Never use the real owner's account or real personal media for adversarial testing.

## 7. Migration reconciliation and rollout gates

1. Obtain and review read-only live diagnostics. Do not replay either historical 0005 file.
2. Compare live state with repository migrations and historical verification notes.
3. Write a forward-only corrective migration with a new unique version only if live evidence proves it is needed.
4. Test that migration against a disposable PostgreSQL/Supabase project, including rollback/recovery planning and existing-row edge cases.
5. Implement metadata and relationship services with server-derived identity and explicit owner filters.
6. Add unit tests plus authenticated two-account integration tests against the disposable environment.
7. Connect Media Library and Mini Cinema first; preserve local drafts and existing project cloud sync.
8. Expand to Image, Music, Voice, Video and Audio branches only after the shared asset contract passes.
9. Keep all assets private by default. Public sharing is a separate opt-in product feature with moderation and revocation controls.

## 8. Explicit non-actions and release boundary

- No SQL was run and no live Supabase object, policy, bucket, grant or migration ledger was changed.
- No migration was renamed, reordered, replayed or applied.
- No asset upload, signed URL, deletion, billing, credit deduction or provider generation was triggered.
- PR #4 remains a draft and must not be merged or deployed without a separate explicit release decision.
- Passing mocked/unit tests does not prove live RLS, Storage policy correctness or two-account isolation.

## 9. Next engineering task

After the live read-only inventory is available, implement the asset metadata and project-link service in a new isolated PR change, beginning with owner-scoped list/detail/attach/detach operations. Upload signing and binary transfer should follow only after bucket policy and content-verification behavior are proven.
