# PWA Studio source-code reality audit

Reviewed: 2026-11-24  
Branch: `fix/supabase-key-compat-2026-11-23`  
Scope: repository source review only. This is not a live Supabase audit and does not certify production state.

## Executive summary

The repository contains a working authenticated FastAPI foundation, AI Companion and Prompt Studio endpoints, community profile/messaging/moderation endpoints, local audio recording/preview, and a source-only unified credit-wallet foundation. Several visible studio areas are intentionally present as interface scaffolds, not connected production capabilities.

The most important architectural gap is that the new credit/pricing services are not yet called by the existing AI generation routes. The current AI endpoints still use a separate per-user/per-endpoint rate limiter and best-effort usage telemetry. There are no credit, pricing, subscription, payment, asset-upload, or media-processing API routes in `backend/app/main.py`.

## 1. Verified backend routes

The current `backend/app/main.py` defines these route families:

| Route family | Current behavior |
|---|---|
| `GET /api/health` | Reports service, environment, configured AI provider, auth and telemetry configuration booleans. |
| `GET /api/auth/me` | Returns authenticated user identity and role. |
| `GET /api/admin/me` | Owner/admin-only identity check. |
| `GET /api/admin/diagnostics/supabase` | Read-only Supabase connectivity diagnostics. |
| `POST /api/chat` | Authenticated AI Companion request, safety check, request-rate limit, provider call, best-effort usage telemetry. |
| `POST /api/prompts` | Authenticated prompt generation, safety check, request-rate limit, provider call, best-effort usage telemetry. |
| `POST /api/reports`, `GET/PATCH /api/admin/reports` | User reports and admin review, including a best-effort status notification. |
| `GET/POST /api/notifications` and read actions | User-scoped notification list/read operations. |
| `/api/community/profile`, `/api/community/users`, `/api/community/profiles/{id}` | Own profile, public-profile search and profile lookup. |
| `/api/conversations`, `/api/messages`, `/api/blocks` | Authenticated direct messaging, edits, self-removal and blocking. |
| `/api/admin/suspensions` | Admin-only account suspensions and revocation. |

Not found in this route file: `/api/credits`, `/api/pricing`, `/api/subscription`, `/api/billing`, `/api/assets`, `/api/media`, upload/download, video rendering, music generation, or TTS endpoints.

The existence of profiles, direct messages, reports and moderation does not mean the public creative feed is complete. No public works feed, likes, comments/replies, creator-follow endpoints, or publication workflow were found in this route inventory.

## 2. Credit and pricing integration gap

Verified source facts:

- `credit_service.py` implements server-side RPC adapters for grant, reserve, settle, release and reconciliation-required transitions.
- `pricing_service.py` calculates versioned quotes and settlements using `Decimal`, server-owned operation/provider/model rules and bounded usage.
- `AI_PRICING_CATALOG` is intentionally empty. A quote without an approved rule fails closed.
- `0013_unified_credit_wallet.sql` defines wallet, reservation and ledger tables plus atomic SECURITY DEFINER RPCs. It is explicitly source-only pending a live migration-ledger/schema audit.
- The SQL revokes direct table access from browser roles and grants service-role execution to the wallet RPCs.
- Unit tests cover the isolated pricing and wallet adapters, including missing price rules and ambiguous usage.
- `main.py` does not import or call `credit_service` or `pricing_service`. Existing `/api/chat` and `/api/prompts` do not reserve or settle credits.

Therefore: the wallet is a tested foundation, not an active billing or metering system. No user-facing credit balance, quote, daily allowance, monthly allowance, checkout or subscription lifecycle is currently exposed by these routes.

### Required next engineering step

Before adding a balance UI, build one bounded server-side operation lifecycle and test it end-to-end: authenticate → server-owned entitlement → server-owned quote → idempotent reservation → provider job → trusted usage settlement/release → durable audit. Start with a low-cost text operation. Do not activate pricing until provider rates, operation ceilings and the credit conversion policy are approved.

## 3. Media and creative workshop reality

| Area | Evidence in source | Current state |
|---|---|---|
| Video creation form | `index.html` `#view-create`; `app.js` `#prepareIdea` handler | Collects an idea and settings. The handler only updates explanatory text; no scenario generation or video provider call. |
| Video editor | `#view-editor` in `index.html` | Explicit empty-state placeholder; timeline, tracks, transitions and subtitles are future work. |
| Media library | `#view-library` in `index.html` | Explicit placeholder; upload and asset management are not connected. |
| Audio workshop | `#view-voice` and `audio-lab.js` | Six-section interface scaffold. Voice catalog and generation are not connected. |
| Microphone recording | `audio-lab.js` uses `getUserMedia` and `MediaRecorder` | Local browser recording and local preview only. Tracks are stopped; preview object URL is revoked on clear/unload. |
| Audio sample import | `audio-lab.js` file input | Accepts browser audio MIME types for local preview only; it does not upload the file. |
| Text-to-speech | Disabled action in audio workshop | Not connected to a TTS provider. |
| Music generation | Disabled action in audio workshop | Not connected to a music provider. |
| Sound effects / audio editing | Interface sections only | No generation, processing or export pipeline verified. |
| Video player / video upload | No video element or video upload route found in the reviewed frontend/backend files | Not implemented as a shared media capability. |
| AI Companion / Prompt Studio | `/api/chat`, `/api/prompts` plus frontend calls | Connected to backend AI provider; usage telemetry is separate from wallet credits. |

The audio sample input advertises common audio formats, but browser preview support depends on the device/browser codecs. This is not a guarantee of server-side conversion, editing or export compatibility.

### Cloud movie-project persistence (verified in frontend source)

The current `app.js` does implement authenticated cloud persistence for Mini Cinema movie-project drafts:

- Signed-in users load their `projects` rows filtered to `project_type = movie`; the browser client relies on Supabase RLS for owner isolation.
- Changes are debounced and upserted to `public.projects` with the authenticated user's ID as `owner_id`; deletions are queued locally as tombstones and sent with explicit owner/type filters.
- The browser also keeps a per-user local copy and reports when cloud synchronization fails; therefore local persistence is a fallback, not proof that every change reached the cloud.
- Guest projects remain device-local under a guest-specific localStorage key; this source does not show guest cloud storage.
- Project settings include the workflow draft and version history snapshot. This is project metadata/content JSON, not uploaded media binaries.

The migration source enables RLS on `public.projects` and defines owner-only select/insert/update/delete policy. This establishes a source-level design for isolation, but the live table, policy, migration ledger and two-account cross-access behavior still require read-only verification and a controlled security test. Do not re-run the migration as part of this audit.

## 4. Storage and migration source risks

The repository contains private-storage migration definitions, but this audit did not inspect the live Supabase migration ledger or live bucket metadata.

Source-level inconsistencies to resolve before any migration automation:

1. Two migration files share the `0005` prefix: `0005_cloud_projects_and_storage.sql` and `0005_moderation_admin.sql`. Migration ordering/ledger identity must be reconciled.
2. `0002_storage_and_moderation.sql` defines `studio-media` at 250 MiB and `studio-exports` at 1 GiB, with both buckets private and policies scoped to the first UUID path segment.
3. `0005_cloud_projects_and_storage.sql` redefines `studio-media` at 100 MiB and re-creates policies for `studio-media`, but does not configure `studio-exports` in that file.
4. The later source definition may intentionally narrow media limits, but the repository does not provide a single authoritative storage contract for all buckets.
5. No dedicated backend asset service, asset schemas or upload/download routes were found. The current frontend audio import is local-only.

Before enabling storage features, define one canonical bucket contract (private/public state, size limit, MIME allowlist, retention, path ownership, signed URL lifetime, malware/content checks and deletion lifecycle), then compare it read-only against live Supabase.

## 5. Security and reliability positives

- Browser Supabase configuration uses a public publishable key; server-only service credentials are kept in backend configuration.
- Backend endpoints use Bearer authentication and role checks for admin routes.
- AI requests have content checks, user suspension checks and a separate request rate limiter.
- The frontend clears account-specific panels/caches when the authenticated user changes.
- Direct messages and profiles are scoped through the authenticated user ID in service calls.
- The credit migration source uses RLS, browser-role revokes, service-role RPC execution grants, per-user wallet locking, idempotency keys and an append-only ledger design.
- The audio sample UI clearly tells users that recording/import remains on-device and requires separate consent before any future voice model creation.

These are source-level observations, not a substitute for adversarial security testing or live policy verification.

## 6. Priority implementation sequence

1. **Close source and migration ambiguity:** resolve duplicate migration prefix, produce canonical storage contract, and complete read-only live Supabase comparison.
2. **Finish credit lifecycle integration:** connect one bounded text operation to quote/reserve/provider/settle/release, with durable job identity and end-to-end tests.
3. **Build asset service:** authenticated upload intents, strict MIME/size checks, per-user object paths, signed downloads, metadata and deletion lifecycle.
4. **Build shared media foundation:** browser capability detection, safe preview, metadata, playback controls, supported-format matrix, and server-side conversion only where an approved processor exists.
5. **Connect workshops incrementally:** TTS/voice, music, sound effects, video generation and editor pipelines, each with measured usage and cost protection.
6. **Build PУЛЬС as an opt-in publication layer:** private-by-default works, publication consent, public feed, likes/comments/follows, notifications, reports and moderation.
7. **Add daily/monthly allowances and paid plans only after costs, policy, billing provider and legal terms are approved.**

## 7. Non-activation boundary

This audit creates no production changes. It does not apply migrations, change Supabase schema/RLS/grants/buckets, activate wallet or pricing, connect payments, charge users, upload/publish user media, or deploy to production.
