# Media Library API — Owner-Scoped Metadata Contract

Status: design contract only. No routes, database tables, Storage operations, or migrations are created by this document.

## 1. Scope of the first backend slice

The first implementation slice is deliberately limited to metadata reads and project-asset relationships:
- list the authenticated owner's ready assets;
- read one asset's safe metadata;
- list assets attached to one owned project;
- attach one owned asset to one owned project;
- detach one relationship without deleting the original asset.

Not in this slice: binary upload, upload signing, signed download URLs, object deletion, transcoding, public sharing, quotas/billing, or admin access to private media.

## 2. Proposed routes

All routes live under the configured API prefix.

| Method | Route | Purpose |
|---|---|---|
| GET | /assets | List the caller's assets; filters: kind, status, usage, limit |
| GET | /assets/{asset_id} | Read safe metadata for one asset |
| GET | /projects/{project_id}/assets | List asset links for one owned project |
| POST | /projects/{project_id}/assets | Attach an existing asset to an owned project |
| DELETE | /projects/{project_id}/assets/{relationship_id} | Detach one relationship |

The existing ProjectAssetAttachRequest and AssetListQuery schemas are the initial request contracts. Unknown fields remain rejected. owner_id, bucket, object key, storage path, signed URL, and status transitions are never client-writable.

## 3. Authentication and authorization invariants

1. Every route requires get_current_user; no guest or anonymous API access.
2. Derive the owner UUID from StudioUser.user_id using canonical_owner_id.
3. Every asset query and mutation includes an explicit owner_id=eq.<verified UUID> filter. Service-role credentials bypass RLS; the filter is mandatory.
4. Before attaching, independently verify that the project is owned by the caller and the asset is owned by the caller and in ready state.
5. A project/asset relationship is created with the verified owner ID on the server. The caller cannot supply it.
6. Detach filters by relationship ID, project ID, and verified owner ID. It never deletes the underlying asset or Storage object.
7. Never reveal whether a guessed foreign asset/project/relationship ID exists. Return the same non-enumerating 404 response for missing and not-owned records.
8. Admin role does not bypass asset ownership in this user-facing API. Any future support workflow must be separate, audited, and purpose-limited.

## 4. Response contract

Asset responses use AssetSafeResponse or a similarly allowlisted projection. They may include only asset UUID; media kind and lifecycle status; safe display name and verified MIME; verified byte size; created/updated timestamps; thumbnail availability flag; and relationship usage count.

Never return bucket IDs, object keys, raw Storage paths, permanent signed URLs, provider credentials, original client-supplied metadata, or private processing diagnostics.

Relationship responses include relationship UUID, project UUID, asset UUID, role, slot, position, and timestamps. They do not embed Storage paths.

## 5. Query and mutation behavior

- GET /assets defaults to status=ready, usage=all, bounded page size, deterministic newest-first ordering. Pagination should use a stable cursor only after the actual schema/index is verified.
- usage=used|unused is derived from relationship existence/count, not a client-provided flag.
- GET /assets/{id} returns 404 for both absent and foreign-owned assets.
- Attach validates role/slot/position through ProjectAssetAttachRequest, verifies both owners, then inserts a relationship. Duplicate behavior must be deterministic and backed by a database uniqueness constraint before implementation.
- Detach removes only the relationship row. The asset remains in the library and remains available to other projects owned by the same user.
- Concurrent attach/detach requests must rely on database constraints/transactions, not read-then-write assumptions in Python alone.

## 6. Service implementation rules

- Keep HTTP route functions thin; put PostgREST access and authorization checks in a dedicated service.
- Use the existing server-only supabase_headers helper. Never put the service-role key in a browser bundle or response.
- Build PostgREST parameters from trusted fixed projections and validated filters. Do not accept arbitrary table names, select strings, sort expressions, or owner filters from the client.
- Validate UUIDs before issuing REST requests.
- Treat upstream storage failures as generic 502/503 responses; do not expose raw upstream response bodies.
- Add structured, privacy-safe audit events for attach/detach without recording filenames, prompts, object paths, or media contents.
- Add unit tests for owner-filter construction and route/service behavior using mocked HTTP responses. Add disposable-Supabase integration tests before claiming database isolation.

## 7. Schema gate — implementation is blocked until resolved

The repository currently has two migration files with version prefix 0005. The storage policy definitions also conflict: 0002_storage_and_moderation.sql defines both media and exports policies, while 0005_cloud_projects_and_storage.sql recreates same-named policies for the media bucket only.

Before implementing PostgREST table access, obtain the read-only live inventory and reconcile the actual migration ledger and handling of both 0005 files; exact public.projects columns and owner constraints; whether an asset metadata or relationship table already exists; RLS, grants, and Storage policies; and existing bucket privacy, limits, and MIME allowlists.

Do not infer the live schema from migration files or create a guessed table contract. Only after reconciliation should a new forward-only migration be designed and tested in a disposable project.

## 8. Acceptance criteria for this slice

- unauthenticated requests receive 401;
- invalid authenticated UUID fails closed;
- user A can list/read/attach/detach only A-owned assets and projects;
- user B cannot list, read, attach, or detach A's records, even with guessed UUIDs;
- attaching the same A-owned asset to multiple A-owned projects is supported;
- detaching one link does not remove the original or its other links;
- foreign and nonexistent IDs produce indistinguishable 404 responses;
- response payloads contain no bucket/object path or signed URL;
- all tests pass, and two-account integration tests pass against a disposable environment;
- no production migration or deployment occurs as part of the implementation PR.

## 9. Explicit non-actions

This document does not create endpoints or database objects. No SQL was run, no Supabase settings were changed, no files were uploaded/downloaded/deleted, no signed URLs were minted, no credits were charged, and no production deployment was performed.