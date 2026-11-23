# Private direct-message attachments — security design

Status: **design and release gate only**. This document does not enable uploads, create a Storage bucket, or claim that malware scanning is deployed.

## Current verified boundary

- Direct messages are persisted through server-side Supabase RPCs.
- The direct-message API currently has no attachment upload or download route.
- The existing chat attachment control remains disabled.
- The repository has a private Supabase Storage adapter for generated image assets, but that adapter is not a direct-message attachment pipeline.
- No deployed antivirus scanner or quarantine-to-clean promotion path has been verified.

Until every release gate below is implemented and tested, the chat must keep file uploads disabled. Do not accept a client-supplied URL or object path as an attachment.

## Initial supported scope

Start narrowly with raster images and PDF documents only:

- PNG, JPEG, WebP
- PDF

Reject SVG, HTML, XML, archives, office macro-enabled documents, executables, scripts, audio, and video in the first release. Add formats only after a separate threat-model review.

Initial maximum: 10 MiB per file, with a small per-message attachment count (for example, 5). Enforce limits while streaming the request body; do not rely only on Content-Length or frontend validation.

## Required upload lifecycle

1. Authenticate the sender and verify that they are an active participant in the target conversation.
2. Enforce per-user and per-conversation rate limits and quota limits before accepting bytes.
3. Stream into a private quarantine bucket using a cryptographically random server-generated object key. Never use the original filename as a storage path.
4. Enforce the byte limit during streaming. Reject empty files and malformed or truncated payloads.
5. Determine the actual format from file signatures and parse the content with hardened libraries. Treat the browser MIME type and filename extension as untrusted hints only.
6. Scan the quarantined object with a deployed malware scanner (for example, ClamAV) using bounded time, memory, and file-size limits. Scanner timeout, unavailable scanner, malformed response, or unknown scan result must fail closed.
7. If clean, copy/promote the object into the private final bucket. If infected or invalid, delete or retain it in quarantine according to a documented incident-retention policy; never expose it to recipients.
8. Insert attachment metadata through a server-only, atomic database function associated with the message, conversation, uploader, verified MIME type, byte size, checksum, scan status, and opaque object key.
9. If metadata persistence fails, clean up the newly uploaded object. Make retries idempotent.
10. Return only safe metadata to the client. Never return a service-role key, storage credentials, public object URL, or permanent signed URL.

## Required download lifecycle

- Authenticate every download request.
- Re-check that the requesting account is a current participant in the exact conversation containing the attachment.
- Require the attachment to be clean and not deleted or quarantined.
- Generate a short-lived signed URL on the server only after authorization, or stream the bytes through an authenticated API route.
- Set safe Content-Type, Content-Disposition, X-Content-Type-Options: nosniff, and a restrictive cache policy.
- Do not permit arbitrary bucket names, object paths, or URL forwarding from the client.
- Revoke access when a user is removed from a conversation or an attachment is deleted; signed URLs should have a short expiry.

## Data model and database security

A future attachment table should include at least:

- opaque UUID primary key;
- conversation_id and message_id foreign keys;
- uploader_user_id;
- private bucket and opaque object key;
- original display filename stored only as sanitized metadata;
- verified MIME type, byte size, SHA-256 digest;
- scan state (pending, clean, infected, failed);
- created_at, deleted_at.

Enable RLS and deny direct table access to anon/authenticated roles. Use narrowly scoped service-role RPCs for create, attach, delete, and metadata lookup. Each RPC must independently verify participant membership and ownership; do not trust IDs supplied by the browser. Add database constraints preventing an attachment from being linked to a message in another conversation.

## Validation and abuse protections

- Allowlist extensions only as a secondary consistency check.
- Verify magic bytes and fully parse supported formats; reject polyglots, malformed files, and decompression bombs.
- Strip image metadata (including EXIF/GPS) before promotion where practical.
- Consider image re-encoding to a safe raster format.
- Sanitize filenames for display; never interpolate them into HTML.
- Apply per-file, per-message, per-user, and global limits.
- Log security events without logging file contents, signed URLs, credentials, or personal file names.
- Add retention and deletion jobs for abandoned quarantine objects and expired attachments.

## Mandatory tests before enabling the UI

1. Non-participant cannot upload, enumerate, or download.
2. Participant cannot access an attachment from a different conversation.
3. Forged MIME type, extension/signature mismatch, SVG, HTML, executable, malformed image/PDF, empty payload, and oversized streaming payload are rejected.
4. Scanner unavailable, timeout, error, and infected verdict all fail closed.
5. Clean file is promoted exactly once; retry does not create duplicate metadata or objects.
6. Database failure triggers safe orphan cleanup.
7. Deleted, quarantined, pending, and infected attachments cannot be downloaded.
8. Signed URL is short-lived and is issued only after authorization.
9. Filename injection, path traversal, encoded separators, and arbitrary object paths are rejected.
10. RLS and function grants are tested in PostgreSQL migration tests.
11. Rate limits and quota enforcement are tested under concurrent requests.
12. The full backend test suite and PostgreSQL migration suite pass in CI.

## Release decision

The attachment control may be enabled only after the private bucket and policies exist, scanner deployment and health checks are verified, the upload/download pipeline is implemented, and the complete test suite above passes on the integration branch. Until then, keeping the control disabled is the intended secure behavior.
