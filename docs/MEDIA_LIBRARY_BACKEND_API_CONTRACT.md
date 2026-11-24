# Media Library Backend API Contract

Status: proposed API contract; no endpoints, database objects, Storage policies, or production settings changed.

## Verified current state

The current FastAPI application exposes authentication, admin diagnostics, reports, notifications, community profiles, conversations/messages/blocks, AI Companion chat, and Prompt Studio routes. It does not currently expose asset/media listing, upload, download, attach/detach, or deletion endpoints.

The server already verifies Supabase access tokens through the Auth JWKS and resolves the authenticated account UUID into a `StudioUser`. Server-side Supabase REST requests use a private service credential helper. This is a privileged server-side integration pattern: every asset operation must independently enforce the authenticated owner scope because service-role requests bypass ordinary end-user RLS enforcement.

No generic bucket browser or client-controlled object-path endpoint should be introduced.

## API surface for the first release

All routes require a valid Bearer access token. The owner UUID is derived from the verified token and is never accepted as an authorization input from the client.

### Read

- `GET /api/assets?kind=&status=&usage=&q=&limit=&cursor=`
  - Returns only assets owned by the authenticated user.
  - Supports bounded pagination and allow-listed filters.
  - Does not return raw Storage object paths or service credentials.
- `GET /api/assets/{asset_id}`
  - Returns safe metadata for one asset only when its owner matches the authenticated user.
- `GET /api/assets/{asset_id}/usages`
  - Returns only the authenticated owner's project references to the asset.

### Upload lifecycle

- `POST /api/assets/uploads`
  - Validates media kind, declared size, filename, and allowed MIME family.
  - Creates a pending upload record owned by the authenticated user.
  - Returns a short-lived upload authorization for a server-generated object key in a private bucket.
- `POST /api/assets/{asset_id}/complete-upload`
  - Verifies ownership and object existence.
  - Verifies actual object size and detected content type against policy.
  - Moves the asset to processing/quarantined/ready/failed as appropriate.
  - Never marks an asset ready solely because the browser says the upload succeeded.

The exact Supabase Storage upload mechanism and signing method must be selected only after inspecting the live bucket configuration and current SDK/API compatibility. Do not assume a bucket name or public/private policy from migration source alone.

### Project relationship

- `POST /api/projects/{project_id}/assets`
  - Body: `{ "asset_id": "...", "role": "...", "slot": "...", "position": 0 }`
  - Verifies the caller owns the project and the asset, and that the asset is ready and compatible with the requested role.
  - Creates an idempotent project-asset relationship.
- `DELETE /api/projects/{project_id}/assets/{asset_id}`
  - Verifies ownership and removes only the relationship.
  - Does not delete the underlying asset.

For MVP, supported project IDs must be checked against the actual project table/model used by Mini Cinema. Do not assume the legacy `studio_projects` table and current `projects` table are interchangeable.

### Delete

- `DELETE /api/assets/{asset_id}`
  - First checks all durable references.
  - If references exist, returns a conflict with safe usage details and does not delete the object.
  - Physical deletion is permitted only after references are removed and the asset is still owned by the caller.
  - Prefer a tombstone/soft-delete state before asynchronous object removal so failures can be retried safely.

## Data and authorization rules

- Derive `owner_id` exclusively from `StudioUser.user_id`.
- Validate UUIDs and constrain every query by both record ID and owner ID.
- Verify project ownership and asset ownership in the same server operation before creating a relationship.
- Use parameterized PostgREST filters and strict allow-lists for sort columns, media kinds, statuses, roles, MIME types and limits.
- Use opaque server-generated Storage object keys; never accept arbitrary bucket names or object paths from the client.
- Keep the bucket private. Issue short-lived access only after re-checking ownership.
- Do not persist signed URLs; they expire. Persist only stable asset IDs and server-side object references.
- Do not return service-role keys, provider credentials, internal object paths, raw provider errors, or private metadata in API responses/logs.
- Enforce maximum object size, request rate, per-account pending-upload count, and upload expiration server-side.
- Treat filename, MIME header, extension and client metadata as untrusted. Validate actual content before marking ready.
- Quarantine unsupported, suspicious, malformed, or unscannable content. Never expose quarantined assets through normal listing or attach APIs.
- Apply consistent 404 behavior for inaccessible foreign IDs where revealing record existence would create an enumeration risk.

## Suggested response shape

Asset list item:
```json
{
  "id": "uuid",
  "kind": "image",
  "status": "ready",
  "display_name": "Storyboard reference",
  "mime_type": "image/webp",
  "size_bytes": 123456,
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "thumbnail_available": true,
  "usage_count": 2
}
```

The example is illustrative only. The server must return only fields that have been verified in the reconciled schema. Do not expose a direct public URL or storage object key.

## Error behavior

- 401: missing, invalid or expired access token.
- 404: asset/project not accessible to this account.
- 409: asset is still referenced, duplicate relationship, or incompatible lifecycle transition.
- 413: upload exceeds configured size limit.
- 415: unsupported media type.
- 422: malformed ID, invalid role, invalid filter or invalid metadata.
- 429: upload/rate/resource limit reached.
- 503: storage subsystem is not configured or temporarily unavailable.

Errors must not contain secrets, raw SQL, signed URLs, or provider response bodies.

## Required automated tests

1. Missing/invalid bearer token is rejected for every asset route.
2. Owner A lists only A's assets; owner B cannot enumerate A's assets.
3. B cannot read, complete upload, attach, detach, download, or delete A's asset by guessing its UUID.
4. A cannot attach an asset to B's project.
5. A cannot attach a pending, failed, quarantined, or unsupported asset.
6. Upload completion independently verifies object existence, actual size and content type.
7. Expired upload authorization cannot be reused.
8. Duplicate attach is idempotent or returns a documented 409; it never creates duplicate rows.
9. Detach does not delete the asset.
10. Delete is blocked while any relationship exists.
11. Signed access is short-lived, generated only after owner verification, and never stored.
12. No service credential or raw Storage path appears in API responses or logs.
13. Account switching and concurrent requests do not cross owner scopes.
14. Guest/local-only assets cannot be uploaded or attached without a user-initiated import flow.

## Preconditions before implementation

- Reconcile live Supabase migration ledger, actual tables/columns/constraints/indexes, RLS, grants, bucket privacy, Storage policies, and object limits.
- Resolve duplicate migration version `0005` and the overlapping Storage policy definitions in a reviewed migration plan.
- Confirm the actual Mini Cinema project table and its ownership semantics.
- Confirm the exact Storage API and private upload/download mechanism against the live project.
- Add isolated backend tests and two-account integration tests using disposable accounts and non-sensitive files.
- Review migration and rollout separately; no production rollout is implied by this contract.

## Explicitly excluded

Public gallery, PULSE feed, likes/comments/follows, cross-user sharing, subscriptions, billing, credit deduction, paid generation, automatic guest import, and production schema changes.
