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
