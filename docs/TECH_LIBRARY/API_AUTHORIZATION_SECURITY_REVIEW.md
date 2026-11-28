# PWA Studio API authentication and object-authorization review

**Review date:** 2026-11-27  
**Scope:** source review of `backend/app/services/auth.py`, `backend/app/main.py`, `backend/app/core/config.py`, Supabase migrations 0002 and 0012, and the character-library cloud test plan.  
**Environment:** feature branch only. No production requests, database queries, migrations, or active security scans were performed.

## Executive result

The API's current authentication dependency verifies Supabase access tokens using the project's JWKS endpoint and checks signature algorithm, issuer, audience, expiry, and subject. Protected routes derive the acting user from this verified token. The current backend does **not** expose character/media CRUD, Storage upload, signed-URL, or generation routes; therefore there is no active API file-object flow to exploit or claim as verified.

The database/Storage design contains useful owner-isolation controls, but the complete object-authorization chain has not been exercised with two authenticated users. Cloud backup and any server-side file handoff remain **NO-GO** until isolated integration tests pass.

## Verified positive controls

1. `get_current_user` requires a Bearer token and returns 401 when missing.
2. Supabase JWT verification uses JWKS and restricts algorithms to ES256/RS256; it checks audience `authenticated`, the expected Supabase Auth issuer, and required `exp`, `sub`, `iss`, and `aud` claims.
3. The API routes reviewed use `Depends(get_current_user)` or `Depends(require_admin)`; the user ID passed to services is taken from the verified `StudioUser`, not from a caller-supplied owner field.
4. Admin authorization is calculated server-side. The browser cannot set its own role.
5. Migration 0002 defines a private `studio-media` bucket and owner-folder policies for SELECT, INSERT, UPDATE, and DELETE using the first path segment and `auth.uid()`.
6. Migration 0012 adds owner RLS to `characters` and `media_assets`, plus a composite foreign key tying `media_assets(character_id, owner_id)` to `characters(id, owner_id)`.
7. No character/media object CRUD, Storage signed URL, image upload, or generation route was found in the reviewed `backend/app/main.py`. Do not infer that future routes inherit security automatically.

## Findings and required actions

### AUTHZ-01 — Admin identity should use immutable Supabase user UUID (high)

The auth service prefers `OWNER_USER_ID`, but falls back to matching the verified JWT email against `OWNER_EMAIL` when the UUID is not configured. The JWT signature is verified, so this is not a client-forgeable role field; however, email-based identity is mutable and should not be the long-term owner assignment.

**Action:** configure `OWNER_USER_ID` with the intended Supabase Auth user's immutable UUID in the deployment environment, verify the owner route, then remove reliance on the email fallback in a separately reviewed change. Never expose this setting or service-role credentials to the browser.

### AUTHZ-02 — No active file API means no proven server-side object authorization (critical before cloud/API handoff)

The current backend has no reviewed endpoints for character/media CRUD, object upload/download, signed URLs, or generation. Therefore, no implementation currently demonstrates the required sequence:

- verify JWT;
- derive owner from verified `sub`;
- query the selected character, project, and media row with owner predicates;
- verify all associations and the expected bucket/path;
- only then read the object or mint a short-lived signed URL.

**Action:** when such routes are introduced, use a dedicated service layer and explicit owner-scoped lookups. Never accept `owner_id`, arbitrary bucket names, arbitrary Storage paths, or a client-supplied signed URL as authorization evidence. Return a generic not-found/forbidden result for foreign UUIDs.

### AUTHZ-03 — Storage folder policies need real cross-user verification (critical before cloud backup)

Migration 0002 uses the intended first-folder-segment convention. The character cloud plan expects paths shaped like `<user-uuid>/characters/<character-uuid>/<reference-id>`. Source inspection does not prove the migration has been applied to any Supabase project or that no additional permissive policies/grants exist.

**Action:** in a disposable Supabase project, test A and B across SELECT/list, INSERT, UPDATE, DELETE, and signed URL creation. Include attempts to move/overwrite an object across owner folders. Inspect all effective policies and grants, not just policy names.

### AUTHZ-04 — Migration 0012 policy creation is not a policy repair mechanism (high)

Migration 0012 creates `characters_owner` and `media_assets_owner` only when a policy with that name does not exist. If a same-named policy already exists with a weaker expression, this migration leaves it unchanged. The preflight currently checks for expression fragments, which is useful as a smoke check but is not a formal proof that the predicate is logically restrictive.

**Action:** before applying migration 0012 in the isolated test project, inspect the full `pg_policies` expressions and effective grants. If an existing same-named policy is not exactly owner-scoped, stop and prepare a reviewed corrective migration. Do not assume that a PASS based on substring matching proves the policy safe.

### AUTHZ-05 — Service-role operations must remain server-only (critical)

The backend uses a service-role secret for server-side telemetry. Any future Storage or database service-role operation would bypass normal RLS enforcement.

**Action:** service-role use must be limited to a small backend-only function after explicit JWT and ownership checks. Never accept client-provided owner identity as a substitute. Never return or log the key, signed URLs, authorization headers, or raw provider/storage error bodies.

### AUTHZ-06 — Message self-delete update must retain participant scope (medium)

The messaging service uses a server-side service-role REST client, which bypasses table RLS. The self-delete flow first selected a message only when the caller was sender or recipient, but its subsequent UPDATE originally filtered only by message UUID. Although the UUID came from that scoped read, the write itself did not repeat the participant predicate.

**Change on 2026-11-27:** the UPDATE now includes both the message UUID and an explicit sender-or-recipient predicate. This makes the authorization condition part of the write operation, not only a preceding read. This is a source-level hardening change; no live API request or integration test was run.

**Required regression test:** with two users, attempt self-delete using a foreign message UUID and assert no row is updated; verify sender and recipient can each hide only their own view and cannot set the other participant's deletion timestamp.

### AUTHZ-07 — Conversation metadata update must retain participant scope (medium)

The direct-message send flow creates or retrieves a thread using the canonical participant pair, then updates `last_message_at` and `updated_at`. Because the REST helper uses the service-role key, RLS is bypassed; the metadata UPDATE originally filtered only by thread UUID.

**Change on 2026-11-27:** the UPDATE now includes the sending user's membership predicate (`user_a_id = sender_id OR user_b_id = sender_id`) alongside the thread UUID. The authorization boundary is therefore present on the write itself.

**Required regression test:** create two unrelated threads for users A/B and C/D; verify a request as A cannot update C/D's thread metadata even if a foreign thread UUID is supplied or a stale/malicious thread object is passed into the service. Confirm the normal participant send path still updates its own thread.

### AUTHZ-08 — Validate externally supplied record identifiers before service-role filters (medium)

Review of moderation and notification services found that several UUID-shaped path/body identifiers were interpolated into PostgREST filters without canonical UUID parsing. Participant/administrator checks still guard the route, and owner filters were present where applicable, but malformed filter values could reach the privileged REST client and produce inconsistent upstream errors.

**Changes on 2026-11-27:** moderation now canonicalizes report IDs before review, suspension target user IDs before creation, and suspension IDs before revocation. Notification read now canonicalizes notification IDs before its owner-scoped UPDATE. Invalid values return HTTP 422 before any service-role request. The notification UPDATE continues to include both notification ID and authenticated user ID.

**Required regression tests:** invalid/non-UUID values must cause HTTP 422 and make zero outbound requests; valid IDs must retain the authenticated owner filter or admin-only route boundary. Verify a user cannot mark another user's notification as read by supplying its UUID.

### AUTHZ-09 — Service-role moderation writes remain privileged route operations (review note)

Report listing/review and suspension listing/revocation use the service-role client. Their protection depends on the FastAPI `require_admin` dependency on every `/api/admin/*` route. Keep this boundary explicit and add route-level tests asserting unauthenticated and ordinary authenticated users receive 401/403, while the configured administrator can proceed. Do not expose these service functions through a user-facing route without adding an explicit authorization predicate to the database operation itself.

### AUTHZ-10 — Report target UUID validation and report attribution (medium)

Report creation correctly derives `reporter_user_id` from the verified `StudioUser`, rather than accepting it from the request body. However, the optional `reported_user_id` was previously passed through to a service-role INSERT without UUID canonicalization.

**Change on 2026-11-27:** when a target account is supplied, the service now canonicalizes it as a UUID before issuing the INSERT; malformed values return HTTP 422 without contacting Supabase. Reporter attribution remains server-derived. This does not prove that a target account exists or that the report is actionable; the database foreign key remains the final existence constraint.

**Required regression tests:** omitted target remains valid; valid target is stored; malformed target returns 422 and causes zero outbound requests; a client cannot override the reporter identity.

### AUTHZ-11 — Atomic moderation state change and audit append (high; implemented in source, verification pending)

The former implementation performed each privileged state mutation and audit insert as separate REST requests, allowing a successful moderation action to lack its audit event if the second request failed.

**Source remediation on 2026-11-27:** migration `0016_moderation_atomic_audit.sql` defines three narrowly scoped `SECURITY DEFINER` RPCs: `pwa_review_user_report`, `pwa_create_user_suspension`, and `pwa_revoke_user_suspension`. Each updates/inserts the moderation record and inserts the matching `admin_audit_log` event in the same PostgreSQL transaction. A failure in the audit insert therefore rolls back the state change. Functions use a fixed `search_path = pg_catalog, public`; EXECUTE is revoked from PUBLIC/anon/authenticated and granted only to `service_role`. The backend now invokes exactly one RPC per moderation mutation and no longer performs a separate audit REST write.

**Tests added:** `backend/tests/test_moderation_atomic_audit.py` checks that service calls use one RPC and do not issue a second audit request. `supabase/tests/0016_moderation_atomic_audit_rollback.sql` adds disposable-database fault injection: it forces the audit insert to fail and asserts report review, suspension creation, and suspension revocation all roll back. The SQL test requires pre-created disposable test users, a pending report, and an active suspension, and is intended for psql only.

**Verification status:** neither test suite nor migration has been executed. The source change is not proof of database behavior until migration 0016 is applied and the rollback test passes in a disposable Supabase project. Do not apply to production or claim the audit trail has been verified.

## Required isolated test matrix

| Test | Attempt | Expected |
|---|---|---|
| AUTH-01 | Missing/invalid/expired token on protected API | 401 |
| AUTH-02 | Valid creator token on admin route | 403 |
| AUTH-03 | User A supplies User B's character/media/project UUID | Generic not-found/forbidden; no metadata or object disclosure |
| AUTH-04 | User B reads/lists User A's Storage path | Denied |
| AUTH-05 | User B inserts, updates, overwrites, or deletes under User A's path | Denied |
| AUTH-06 | User A changes first path segment to User B UUID | Denied |
| AUTH-07 | Client supplies forged owner_id in request body | Ignored or rejected; owner derived from JWT |
| AUTH-08 | Same-named pre-existing RLS policy is weaker | Preflight fails; migration is not treated as repair |
| AUTH-09 | Admin identity after OWNER_USER_ID is configured | Only exact configured auth UUID receives admin role |
| AUTH-10 | Service-role key absent from frontend bundle, responses, and logs | No secret exposure |

## Activation decision

**NO-GO** for cloud backup, API-mediated reference upload/download, signed URL creation, external image/video provider handoff, or generation workers until:
- immutable admin UUID configuration is confirmed;
- exact effective RLS and Storage policies are inspected;
- two-user integration tests pass in a disposable Supabase project;
- future object routes implement owner-scoped lookups before object access;
- image decoder and resource bounds are implemented and tested;
- upload failure compensation and orphan cleanup are tested.

This document records source-review findings only. It does not claim a live penetration test, migration execution, test run, or production security certification.

### AUTHZ-12 — Admin route guard and immutable owner identity regression coverage (high; tests added, execution pending)

Source review confirms that administrative report and suspension routes use `Depends(require_admin)`, and `require_admin` accepts only the server-derived `StudioUser.role == "admin"`. `get_current_user` derives the subject from a verified Supabase JWT; when `OWNER_USER_ID` is configured, that immutable UUID takes precedence over the email claim. The transitional `OWNER_EMAIL` fallback remains active when `OWNER_USER_ID` is empty, so production must be checked to confirm the UUID setting is present.

**Tests added on 2026-11-27:** `backend/tests/test_admin_authorization.py` covers JWT verification parameters, UUID-over-email precedence, missing Bearer token (401), creator denial (403), server-resolved admin acceptance, creator denial across all current `/api/admin/*` routes, admin access to read-only admin routes, and proof that report review/suspension actor IDs are taken from the authenticated server-side `StudioUser` rather than request payloads. Tests use mocked auth/storage and do not contact Supabase.

**Verification status:** tests have not been executed. The deployment environment's actual `OWNER_USER_ID` value has not been inspected; do not infer it from source code. Before production readiness, verify that it equals the intended Supabase Auth UUID and that a normal creator receives 403 from every administrative route. Do not expose environment values or secrets in logs/screenshots.

### AUTHZ-13 — Cross-owner media/project association and effective policy review (high; source hardening added, database verification pending)

The reviewed schema had owner-only RLS on `projects`, `characters`, and `media_assets`. Character-to-media links already used a composite foreign key `(character_id, owner_id) -> characters(id, owner_id)`. However, `media_assets.project_id` used only a simple foreign key to `projects(id)`; a row owned by account A could therefore reference a project owned by account B if inserted by a path with sufficient table privileges. This is a relational integrity gap even when row-level owner policies are correct.

A second source-level inconsistency was found: migration `0002_storage_and_moderation.sql` defines owner-path policies for both private buckets, but `0005_cloud_projects_and_storage.sql` drops and recreates the same policy names for `studio-media` only. Applying both in order leaves `studio-exports` outside those named policies. Additional permissive policies in PostgreSQL can also widen access because permissive policies combine with OR; checking only one expected policy name is insufficient.

**Source remediation on 2026-11-27:** new draft migration `0017_owner_scoped_media_associations.sql` adds a unique key on `projects(id, owner_id)`, replaces the simple media/project FK with a composite `(project_id, owner_id)` FK, and uses column-specific `ON DELETE SET NULL (project_id)` so deleting a project does not null the media owner's required identity. It recreates the named character/media owner policies with both `USING` and `WITH CHECK`, and restores owner-path policies for both private buckets. The migration is intended to fail rather than silently accept pre-existing cross-owner project links.

**Verification support added:** `backend/tests/test_media_owner_isolation_contract.py` statically checks the migration and schema contracts. The read-only diagnostic `supabase/diagnostics/inspect_cloud_storage.sql` now lists every effective policy for relevant tables, foreign-key/unique constraints, table grants, and presence of the new composite FK. These are source-level checks only; they do not prove live RLS or Storage behavior.

**Required isolated integration tests before cloud sync:** use two real test accounts A/B and verify each account cannot SELECT, UPDATE, DELETE, or attach another account's character, project, media row, or object path; verify both buckets separately; test upload, list, download, overwrite/move, and signed URL creation; inspect all effective policies and grants. Confirm project deletion nulls only `project_id` while preserving `owner_id`. Do not apply migration 0017 to production as part of this review.


## Follow-up verification — 2026-11-28 (supersedes earlier scope statements where noted)

The original review above was written before the Character Library media API was added. Its statements that no character/media API routes exist are historical and are superseded by this follow-up section.

### Implemented media API path

- Authenticated routes now exist for listing a character's reference status, uploading a reference, reading private image bytes through an authenticated proxy, and obtaining a short-lived signed URL for an owned ready asset.
- Upload derives owner identity from the verified `StudioUser`, loads the character through an owner-filtered repository, validates the image bytes, creates deterministic idempotency identifiers, and commits a reservation before the Storage upload. The asset is not considered ready until the independent verification flow completes.
- Read/access routes reload the asset using both asset UUID and authenticated owner UUID, verify linked project/character ownership, require ready status and the private bucket, and validate the Storage key. The path's resource UUID is now compared with the exact linked `character_id` or `project_id`, not merely with an allowed resource kind.
- The byte proxy bounds downloads to 8 MiB, fully decodes/validates the image, checks digest, size, width, and height against the reservation, and returns private no-store/nosniff headers. The signed URL path is host-pinned to the configured Supabase project and has a 60-second TTL.
- Browser-facing metadata excludes owner IDs, bucket, Storage path, and internal metadata.

### Admin identity and route checks

- `get_current_user` verifies Supabase JWT signature via JWKS, issuer, audience, allowed algorithms, expiry, and subject. `require_admin` gates all current `/api/admin/*` routes.
- Regression tests cover immutable `OWNER_USER_ID` precedence over email, case-insensitive UUID comparison, creator denial across current admin routes, missing Bearer rejection, and server-derived moderator identity.
- The feature-branch backend suite passed these tests in CI run `46098849243`. This is mocked route/auth verification, not inspection of live deployment environment values.
- The `OWNER_EMAIL` fallback still exists when `OWNER_USER_ID` is unset. The deployment setting has not been inspected; production must explicitly confirm the immutable UUID is configured before readiness is claimed.

### Supabase key compatibility and CI

- The audited service-role REST/Storage services send every key as `apikey`; they add `Authorization: Bearer` only for legacy JWT-form keys beginning with `eyJ`. Modern `sb_secret` values are not treated as JWTs.
- The scan of the remaining media and moderation service modules found no unconditional Bearer header. The corresponding credential handling is covered by regression tests for both key formats.
- Full CI run `46098849243` completed successfully on feature commit `52a446b`: backend unit tests, disposable PostgreSQL integration, and real-browser account-isolation tests all passed. The PostgreSQL job ran migrations and concurrency/stress harnesses only against its disposable database.
- The earlier code-only CI run `46098844078` failed because a legacy test fixture still expected a Bearer header for a modern secret key. The test fixture was corrected in `52a446b`; the complete follow-up run passed.

### Remaining production-readiness limits

1. No live Supabase effective-policy/grant inspection or two-real-account Storage penetration test has been performed.
2. No live deployment value for `OWNER_USER_ID` has been inspected.
3. The independent media verifier/cleanup workers and their operational scheduling/monitoring need a production-safe runbook and explicit deployment review.
4. The content safety layer is an input keyword/pattern guard, not a comprehensive moderation service; generated-output moderation and image/video moderation remain separate requirements.
5. AI budget reservation is still not wired to `/api/chat` or `/api/prompts`; passing isolated SQL tests is not production spend protection.

**Current decision:** the media API has meaningful source-level ownership, integrity, and privacy controls and its isolated CI suite passes. This does not constitute a live Supabase policy audit, production penetration test, deployment verification, or security certification. Do not deploy or apply migrations from this review without explicit approval.


### Follow-up verification — 2026-11-28: worker lifecycle and moderation boundaries

#### Private media background workers

- Both worker entry points are implemented as private polling processes: `python -m app.workers.media_outbox_worker` independently verifies uploaded character images, and `python -m app.workers.media_cleanup_worker` deletes only server-claimed tombstoned objects. Neither exposes an HTTP listener.
- Both use bounded polling, finite claim leases, fresh UUID claim tokens, capped retry delays, bounded attempts (8), and graceful SIGTERM/SIGINT shutdown. The verification worker fully downloads/decodes and checks the reserved fingerprint; the cleanup worker validates the complete claim and canonical owner/character/object path before Storage access.
- The cleanup SQL uses row locks, `SKIP LOCKED`, idempotency keys, claim-token/lease fencing, exact-reference checks, tombstones, and a separate finalization RPC. Repeated Storage deletion after an uncertain acknowledgement is designed to be safe because an already-absent object is treated as success by the Storage delete adapter. Exhausted/invalid claims go to dead letter; there is no supported automatic dead-letter requeue API. Do not manually edit queue rows.
- **Deployment boundary:** the current Dockerfile starts only Uvicorn and `render.yaml` declares only the API web service. Neither worker is started by the current API deployment. API health therefore does not establish queue processing. A future deployment needs two separate private worker processes, one per command, with restart policy, bounded resources, SIGTERM grace, and queue-age/dead-letter/error monitoring. No worker service was provisioned or started by this review.
- Regression test coverage includes malformed claims, no Storage access for invalid claims, storage-delete/acknowledgement uncertainty, lease expiry and fresh-token reclaim. CI run `46099345030` completed successfully: backend unit tests, disposable PostgreSQL media-cleanup integration, and real-browser account-isolation tests all passed. This run did not deploy or execute a worker against production objects.

#### Reports, restrictions, and moderation

- Report creation is authenticated and derives reporter identity from the verified session. Database constraints bound category, description, and content reference. Admin review and suspension routes are behind `require_admin`; moderator identity is passed from the server-derived `StudioUser`, not a client-supplied actor field.
- Review, suspension creation, and revocation each use a single SECURITY DEFINER RPC with a fixed search path and service-role-only EXECUTE grants. State mutation and append-only audit insertion occur in the same transaction; disposable-database fault-injection tests verify rollback if the audit insert fails.
- The current generation input guard is explicitly a conservative regex/keyword first layer, not complete moderation. It does not provide semantic classification, generated-output review, image/video moderation, or a complete appeals workflow. Reports are stored and can be reviewed, but there is no end-to-end automated moderation pipeline or appeals endpoint established by this review.
- Suspension enforcement is currently explicit at selected community routes and should not be assumed to cover every generation, messaging, upload, or media operation. A route-by-route policy matrix and central enforcement design are still required before treating restrictions as platform-wide.
- Report abuse controls (durable per-user quotas/rate limits, duplicate clustering, evidence retention/deletion policy, reviewer access workflow, and escalation/appeal handling) remain product/security design work. The 2026-11-28 route review confirmed that `POST /api/reports` currently has no rate-limit or idempotency guard. Do not add a broad output regex filter as a substitute: it would create false positives without a policy, appeal path, and test corpus.

#### Report endpoint abuse review — 2026-11-28

- `POST /api/reports` requires a verified user session and uses the authenticated subject as `reporter_user_id`; clients cannot choose the reporter identity.
- The request schema caps the description at 4,000 characters and content reference at 500 characters, and restricts categories to a fixed allowlist.
- Unlike `/api/chat` and `/api/prompts`, report creation currently has no rate-limit/quota call and no idempotency key. A signed-in account can therefore submit repeated reports within the schema limits. Authentication and field validation do not prevent report flooding.
- Do not add a process-local limiter and call it sufficient: multiple API workers/instances would each have an independent counter. A durable per-user quota or shared atomic limiter should be designed with explicit retry semantics, duplicate handling, and audit-safe retention before implementation.
- Keep report submission available to suspended users so they can still report abuse; suspension checks should not accidentally close the safety/reporting channel. Reviewer access and evidence lifecycle still need a documented policy.

#### Remaining blockers and decision

1. Provision and monitor the two private workers before relying on asynchronous media verification or cleanup in a live environment; confirm queue age and dead-letter alerting.
2. Design a governed moderation pipeline covering input, generated text, uploaded/generated media, reviewer actions, appeals, and scoped restriction enforcement.
3. Complete route-by-route suspension enforcement and report-abuse controls before claiming platform-wide moderation.
4. Keep dead-letter recovery manual/escalated until a reviewed, audited recovery protocol exists.
5. Live Supabase policy/grant checks, real two-account storage tests, immutable admin UUID configuration, and production deployment verification remain outstanding.

**Decision:** source-level worker and moderation boundaries are now documented. CI run `46099345030` passed all three jobs. This is not a production deployment, live policy inspection, queue-processing proof, or security certification. Do not merge, deploy, or apply migrations without explicit approval.
