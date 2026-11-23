# Private direct-message attachments: security gate

## Current state

Direct-message attachments are intentionally **not enabled**. The current message API accepts plain-text bodies only. The existing `studio-media` adapter is designed for generated image assets; it is not a message-attachment service and does not provide malware scanning or conversation-membership authorization for file downloads.

The chat composer therefore shows a disabled attachment control. Do not enable it by wiring a browser upload directly to a public bucket or by reusing generated-media object paths.

## Required release gates

1. Create a dedicated private Storage bucket for direct-message attachments. Keep public access disabled and apply strict bucket-level size and MIME restrictions.
2. Accept uploads only through an authenticated backend endpoint. Derive the sender ID from the authenticated session; never trust a client-supplied owner ID.
3. Verify conversation membership and active messaging restrictions before accepting an upload and again before issuing any download URL.
4. Enforce a bounded request body and per-file size limit before buffering. Generate opaque server-side object names; do not use user-provided filenames as storage paths.
5. Validate file extensions, declared MIME types, and file signatures independently. Reject HTML, SVG, executable formats, archives, and unknown types by default.
6. Upload new objects to a private quarantine area. Mark metadata as pending scan and do not make the object downloadable.
7. Run a real malware scanner (for example, a separately deployed ClamAV service) with bounded time and resource limits. If the scanner is missing, unavailable, times out, or returns an indeterminate result, fail closed and keep the object quarantined.
8. Only after a clean scan, move or copy the object into the private conversation area and mark its metadata clean. Persist size, detected MIME, checksum, scan engine/version, scan time, uploader, conversation, and storage path.
9. Issue short-lived signed download URLs only after rechecking participant membership, clean scan status, object metadata, and path ownership. Never persist or expose permanent public URLs.
10. Add rate limits, upload quotas, audit events, deletion/retention handling, orphan cleanup, and tests for cross-conversation access, spoofed MIME, oversized payloads, malicious samples, scanner outage, and expired links.

## Allowed initial formats

Start with a deliberately small allow-list: PNG, JPEG, WebP, and PDF. Add other document formats only after format-specific validation and malware-scanning tests. Do not accept SVG or HTML as images.

## Activation criteria

The attachment button must remain disabled until the private bucket and policies are verified in the deployed Supabase project, the scanner is deployed and configured, backend upload/download endpoints are covered by security tests, and a two-account end-to-end test proves that one conversation participant cannot access another conversation's files.
