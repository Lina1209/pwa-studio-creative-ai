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

**Tests added on 2026-11-27:** `backend/tests/test_admin_authorization.py` covers JWT verification parameters, UUID-over-email precedence, missing Bearer token (401), creator denial (403), server-resolved admin acceptance, creator denial across all current `/api/admin/*` routes, and admin access to read-only admin routes. Tests use mocked auth/storage and do not contact Supabase.

**Verification status:** tests have not been executed. The deployment environment's actual `OWNER_USER_ID` value has not been inspected; do not infer it from source code. Before production readiness, verify that it equals the intended Supabase Auth UUID and that a normal creator receives 403 from every administrative route. Do not expose environment values or secrets in logs/screenshots.
