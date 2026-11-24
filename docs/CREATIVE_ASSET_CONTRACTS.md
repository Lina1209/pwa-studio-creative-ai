# Creative Asset Contracts

Status: proposed application contract. No API endpoints, database tables, buckets, or migrations are created by this document.

Related architecture: `docs/CREATIVE_ASSET_STORAGE_ARCHITECTURE.md`.

## 1. Contract principles

1. The authenticated owner is derived from the verified access token on the backend. Requests never choose their own `owner_id`.
2. A storage object is not a usable asset until the backend verifies it and changes its lifecycle state to `ready`.
3. Projects and studio branches reference canonical asset IDs. They do not copy asset binaries by default.
4. Asset metadata, project relationships, provider usage, and credit accounting are separate concerns.
5. Client-supplied MIME type, filename, byte size, checksum, project ID, and object path are untrusted and must be validated.
6. All list and detail responses are owner-scoped. No public bucket URL or permanent signed URL is returned.

## 2. Canonical asset resource

Proposed safe response shape:

```json
{
  "id": "uuid",
  "kind": "image",
  "display_name": "Forest concept",
  "mime_type": "image/webp",
  "size_bytes": 482190,
  "checksum_sha256": "hex-or-null",
  "width": 1536,
  "height": 1024,
  "duration_ms": null,
  "status": "ready",
  "source": {
    "branch": "image_studio",
    "operation_id": "uuid-or-null"
  },
  "created_at": "ISO-8601 timestamp",
  "updated_at": "ISO-8601 timestamp"
}
```

The response deliberately omits storage bucket/object key, owner UUID, credentials, permanent signed URLs, prompt text, private source text, and raw provider responses. Optional technical metadata is nullable; unknown dimensions or duration remain null, not zero.

### Allowed kinds

- `image`
- `video`
- `audio`
- `music`
- `voice`
- `document`
- `other`

Detected content type must be consistent with the declared kind and server-side allowlist. The allowlist is purpose-specific; arbitrary executable or active content is not accepted.

### Lifecycle states

- `pending`: upload intent created; object not verified.
- `processing`: verification or approved scanning/transformation underway.
- `ready`: checks passed; available for authorized reuse.
- `quarantined`: security or policy review required; normal access blocked.
- `failed`: upload or processing failed.
- `deleting`: deletion requested; access and new references blocked.
- `deleted`: object cleanup confirmed.

Only the backend may transition lifecycle state. The browser cannot mark an asset ready, clear quarantine, or claim deletion succeeded.

## 3. Upload intent

Proposed request:

```json
{
  "kind": "image",
  "display_name": "Forest concept",
  "declared_mime_type": "image/webp",
  "declared_size_bytes": 482190,
  "idempotency_key": "client-generated-random-key"
}
```

Validation:
- `kind` belongs to the controlled vocabulary.
- `display_name` is trimmed, length-bounded, and plain text.
- MIME type is checked against a purpose-specific server allowlist.
- Size is a positive integer within configured limits.
- Idempotency key is bounded and scoped to owner and operation.
- No client-provided owner, bucket, object key, storage path, lifecycle state, or credit amount is accepted.

Proposed response:

```json
{
  "asset_id": "uuid",
  "status": "pending",
  "upload": {
    "method": "PUT-or-provider-specific",
    "url": "short-lived-upload-url",
    "expires_at": "ISO-8601 timestamp",
    "required_headers": {}
  }
}
```

The upload URL is ephemeral; never persist it in project data, logs, analytics, or the asset record. The exact upload mechanism depends on verified Supabase Storage configuration.

## 4. Completion and verification

Proposed request:

```json
{
  "checksum_sha256": "optional-hex-digest"
}
```

The backend obtains the object key from its own pending record, never from the request. It verifies owner and intent validity, object existence, actual size, actual content type/signature, and checksum where trustworthy. Completion retries are idempotent and cannot create duplicate assets.

Failed verification leaves the asset unavailable and follows a safe failure/quarantine path. It never appears in the normal ready-asset listing.

## 5. List and detail behavior

Proposed list filters:
- `kind`: optional controlled kind;
- `status`: safe server-supported status (normal users normally see `ready` only);
- `project_id`: optional project relationship filter;
- `cursor`: opaque pagination cursor;
- `limit`: bounded page size.

Response:

```json
{
  "items": [],
  "next_cursor": null
}
```

The server always applies the authenticated owner filter. A guessed asset UUID belonging to another user returns a non-disclosing not-found response.

## 6. Access URLs

The backend authenticates the user, loads the asset under that owner, requires `ready` state, checks the requested purpose, then creates a short-lived signed URL or streams the object. Signed URLs are bearer capabilities and must not be logged or embedded in long-lived records.

## 7. Project relationships

Proposed attach request:

```json
{
  "asset_id": "uuid",
  "role": "scene_image"
}
```

Initial roles: `cover`, `scene_image`, `source_video`, `soundtrack`, `voiceover`, `sound_effect`, `reference`, `export`, `other`.

Rules:
- Project and asset must belong to the authenticated owner.
- Asset must be `ready`.
- Relationship uniqueness is enforced for the relevant project/asset/role tuple unless product rules explicitly allow duplicates.
- Detaching removes only the relationship, not the asset.
- Deleting a project does not delete shared assets still referenced elsewhere.
- Cross-account sharing is outside this contract.

## 8. Error contract

Suggested machine-readable codes:
- `asset_invalid_request`
- `asset_type_not_allowed`
- `asset_too_large`
- `asset_upload_expired`
- `asset_not_ready`
- `asset_not_found`
- `asset_project_not_found`
- `asset_idempotency_conflict`
- `asset_storage_unavailable`
- `asset_quarantined`

Do not return raw Storage errors, signed URLs, object keys, credentials, or stack traces.

## 9. Required tests

### Ownership and isolation
- User A cannot list, read, attach, access, or delete User B's asset.
- User A cannot attach an asset to User B's project.
- Account switching cannot reuse stale in-memory results.

### Upload integrity
- Invalid MIME, mismatched content, empty file, oversized file, and path traversal are rejected.
- An intent cannot be completed by another account.
- Expired/abandoned intents cannot be finalized.
- Duplicate intent/completion retries are idempotent.
- Client-supplied path, bucket, owner ID, status, and size cannot override server decisions.

### Lifecycle and deletion
- Pending, failed, quarantined, and deleting assets are not exposed as ready.
- Referenced assets cannot be physically deleted without the defined detach/confirmation flow.
- Cleanup failure remains retryable and is not reported as completed.
- Repeated deletion requests do not corrupt state.

### Reliability and privacy
- Storage timeout does not produce a false ready state.
- Responses omit private prompts, object keys, credentials, and permanent URLs.
- Logs redact signed URLs and authorization data.
- Pagination is stable and owner-scoped.

## 10. Implementation gate

Before implementation:
1. Reconcile the live Supabase migration ledger and actual schema.
2. Resolve duplicate `0005` migration naming and overlapping Storage policies without blindly rewriting historical migrations.
3. Design a new forward-only migration version based on the verified live ledger.
4. Test schema and Storage behavior in a disposable environment.
5. Implement backend contracts and automated tests before wiring the asset shelf UI.
6. Enable one branch at a time, beginning with Media Library and Mini Movie Studio.

No paid storage quota, credit deduction, provider generation, or production migration is authorized by this document.
