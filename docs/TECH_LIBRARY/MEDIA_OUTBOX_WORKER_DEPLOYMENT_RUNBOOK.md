# Media outbox verification worker — deployment runbook

Status: **prepared, not deployed**. This document describes a future isolated deployment. It does not create a Render service, change `render.yaml`, apply SQL, or enable uploads in the application UI.

## 1. Current architecture

- The API is the only service declared in the current `render.yaml`.
- The API container starts Uvicorn; it does not start a queue consumer.
- The verification consumer is a separate CLI process:
  `python -m app.workers.media_outbox_worker`.
- The consumer polls the media outbox, claims work with a lease/fencing token, downloads the private Storage object through the server-side media reader, decodes and validates the image, then records completion or retry through the repository RPCs.
- An uploaded object is **not ready for use** merely because the upload endpoint returned successfully. It must reach the verified `ready` state.
- The worker must not be started as a second process inside the API web service. It needs an independently managed process lifecycle.

## 2. Required deployment shape

Create a dedicated Background Worker service from the same repository and Dockerfile, with the same pinned branch/commit as the API release being tested.

- Dockerfile: `./backend/Dockerfile`
- Docker context: repository root (`.`)
- Start command override: `python -m app.workers.media_outbox_worker`
- Process type: background worker / non-HTTP service
- Do not configure a public URL, web health-check path, or inbound port for this process.
- Keep the API service unchanged. Do not add the worker to the production blueprint until a separately approved rollout.

The worker and API must run compatible code and migrations. Do not point a feature-branch worker at the live production database.

## 3. Environment and secrets

Provide only the settings needed by the worker:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` — server-side secret only; never expose it to a browser, logs, build arguments, or a public endpoint.
- `APP_ENV` — set to the environment name appropriate for the isolated test deployment.

The worker does not need DeepSeek, Gemini, OpenAI, Anthropic, or other AI-provider keys. Do not copy AI secrets into the worker environment. Do not print secret values while diagnosing configuration.

The current settings object reads Supabase URL and service-role key from environment variables. The worker uses the service role only for its server-side queue/storage operations.

## 4. Safe isolated validation sequence

Use a disposable Supabase project and a private test bucket, never the production project:

1. Apply only the reviewed media migrations to the disposable database after checking migration prerequisites.
2. Confirm the worker's service-role permissions and private bucket configuration in that disposable environment.
3. Start one worker instance with the command above; initially keep concurrency at one.
4. Submit a small, known-good PNG through the test API and record its owner, asset ID, object key, digest, and outbox event ID.
5. Observe the state transition from the upload reservation through object upload and verification to `ready`.
6. Confirm the verified content endpoint returns the same bytes and digest only to the owning test account.
7. Repeat with invalid image bytes, MIME mismatch, oversized content, missing object, and a different owner. Confirm failures do not become `ready` and do not disclose private content.
8. Stop the worker during a leased task. Confirm lease expiry/reclaim and fencing prevent an old worker from completing a newer claim.
9. Restart the worker and confirm retries are bounded and terminal failures remain observable.
10. Delete test data only through the disposable project's cleanup procedure.

Do not use real user files, production credentials, or paid AI providers in this test.

## 5. Operational checks before any rollout

A future rollout is blocked until all are true:

- A disposable end-to-end test proves upload → outbox → private-object download → real image decode → verified `ready` → owner-authorized read.
- Retry, lease expiry, stale-worker fencing, graceful shutdown, and duplicate delivery have been tested.
- Logs contain event/asset identifiers and safe error codes, but no secrets, signed URLs, or image bytes.
- Worker health is monitored through process status and queue age/backlog; an HTTP health endpoint is not assumed.
- Alerting exists for repeated failures, growing backlog, and events stuck beyond the expected lease/retry window.
- A documented rollback/stop procedure exists and does not delete user media.
- API/UI upload and restore flows are enabled only after the worker is demonstrably running and the complete pipeline passes.

## 6. Current limitations and non-actions

- No worker service is currently declared in `render.yaml`.
- No worker has been deployed or started against production.
- No production database or Storage bucket has been accessed or changed for this runbook.
- The media upload UI remains disconnected from the binary transfer adapter.
- The current CI worker test uses a real generated PNG and the actual decoder, but mocks the HTTP transport. It is not an end-to-end Supabase Storage or queue test.
- A passing CI run does not establish that a production queue consumer exists.

## 7. Change-control gate

Before creating any real worker service, obtain explicit approval for the target environment and service provisioning. First deploy and validate against disposable infrastructure. Production rollout requires a separate approval after evidence from the isolated test is reviewed.
