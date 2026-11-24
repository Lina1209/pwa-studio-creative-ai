# PWA Studio — complete workshop, media, export, and community inventory

Last reviewed: 2026-11-24
Status: source-based product inventory and roadmap clarification. Documentation only; no UI, media processing, provider integration, billing, quota, or database behavior is activated here.

## 1. Readiness vocabulary

- Present in source: a page, navigation area, or local interaction was found.
- Partial/local: only a draft, planning, local recording, or preview behavior exists.
- Backend foundation: supporting code exists, but the complete user workflow is not connected.
- Planned/not connected: intended capability, not a verified working feature.
- Not audited live: repository evidence cannot establish deployed or Supabase state.

A menu item is not proof of a working generation service. A mentioned format is not proof that the application can encode or export it.

## 2. Shared platform trunk

| Area | Current source evidence | Remaining work |
|---|---|---|
| Account/authentication | Supabase sign-in, sign-up, password-reset UI; backend JWT verification | Verify account switching, two-account isolation, recovery and session expiry |
| Workspace/dashboard | Creative Control Center and dashboard surfaces | Complete truthful live status and usage summary |
| Projects/versions | Mini Cinema local drafts, edit/copy/delete and local version history; cloud-sync code exists | Reconcile live schema; test cross-device sync, conflicts, deletion and restore |
| AI Companion | Backend chat endpoint and conversation-history foundation | Verify deployment, isolation, error recovery and measured usage |
| Prompt Studio | UI and backend prompt endpoint in source | Verify live workflow, prompt library, versioning and provider behavior |
| Media Library | Navigation/empty-state surface; no complete asset upload UI or asset CRUD API found | Private upload, verified metadata, preview, access, reuse, deletion and export |
| Character Library | Database foundation is referenced in roadmap; complete workflow not verified | Audit live schema/RLS, then owner-scoped character/reference management |
| Safety/moderation | Backend safety, reporting, messaging and moderation foundations | Complete policy enforcement, appeals, moderation UI, audit trail and multimodal checks |
| Notifications/messages | Backend services/routes exist in source | Verify delivery, read state, preferences and user/admin isolation |

## 3. Creative workshops

| Workshop | Current source status | Target capability |
|---|---|---|
| Mini Cinema / Film Studio | Local project workflow and planning stages; no connected AI screenwriter/storyboard or complete film render | Stories, characters, scenes, storyboard, shot planning, assembly and export |
| Video Studio | Video-related navigation/planning surfaces; generation not connected | Generate clips, trailers and music videos; edit/transform clips; regenerate scenes |
| Video Editor | Planning/editor surface; timeline rendering and MP4 export not connected | Timeline, trim/split/merge, transitions, overlays, subtitles, audio tracks and render |
| Music Studio | No connected music-generation provider verified | Songs with own/AI lyrics, vocal/instrumental modes, broad free-form styles, arrangements and variations |
| Audio Studio | UI and local microphone/file preview/recording described in roadmap; no upload or audio-generation service connected | Record, import, trim, split, join, mix, normalize, effects, extract audio from video and export |
| Voice Studio | Voice-workshop UI exists; voice generation/cloning not connected | Voice recording, narration, TTS, character dialogue, transcription and consent-gated voice workflows |
| Image Studio | Image generation/editing provider integration not verified | Generate/edit/upscale images, illustrations, character references and scene concepts |
| Text and Script Studio | Script/scenes and local production notes exist within Mini Cinema; independent full workflow not verified | Stories, scripts, dialogue, treatments, shot lists and reusable text assets |
| Prompt Studio | UI and backend prompt endpoint exist in source | Create, improve, translate, adapt, organize and reuse prompts |
| AI Companion | Backend chat and conversation history foundations exist | Creative assistant with project-aware context and safe cross-workshop hand-offs |
| ПУЛЬС | Approved product concept; complete public gallery/community not verified | Voluntary gallery, creator pages, follows, likes, comments, categories, trends, notifications, chat and moderation |

## 4. Shared media tools and playback

These are shared platform capabilities, not separate generation studios.

| Tool | Target behavior | Current status |
|---|---|---|
| Audio player | Play/pause, seek, duration, volume, playback position and audio previews | Complete shared player not verified |
| Video player | Play/pause, seek, volume, fullscreen, speed and subtitles/captions where available | Complete shared player not verified |
| Microphone capture | Record, permission handling, timer, preview and save | Local recording/preview exists in Audio Studio; cloud save not connected |
| Import | Select supported files, validate actual size/type and preserve originals | Complete shared upload workflow not verified |
| Export/download | Download user-owned outputs with format and quality choices | General export pipeline not verified |
| Conversion/transcoding | Convert only where a real encoder/decoder is implemented and resource limits are enforced | Planned |
| Audio editing | Trim, split, join, mix, gain, fade, normalize and attach tracks | Planned |
| Video editing | Trim, split, join, reorder, crop, subtitles and timeline assembly | Planned/partial planning UI |
| Audio extraction | Extract an audio track from an authorized video file | Planned |
| Codec/container support | Detect codecs/containers and explain unsupported files | Not verified; must be tested explicitly |
| Metadata inspection | Read duration, dimensions, sample rate, channels, codec, bitrate and size | Planned |
| Media safety | Enforce size/duration limits, validate content, quarantine suspicious uploads and scan where feasible | Architecture planned; runtime pipeline not connected |

## 5. Format and quality policy

Initial practical export targets:
- Video: MP4 as the primary broadly compatible download format.
- Audio/music: MP3 as the primary broadly compatible download format.

Candidate additional formats include WAV/FLAC for audio and WebM/MOV for video. These are roadmap candidates, not current promises. Do not claim all formats or lossless quality unless the exact encoder, codec, device compatibility and output have been verified. Preserve originals when conversion creates a derivative. Show actual format, resolution, duration, bitrate/quality profile and file size when known.

Free access should retain a useful standard export path. Paid plans may unlock higher resolution, bitrate, advanced codecs/formats, larger projects, longer durations or more concurrent processing, subject to real provider and infrastructure support. A subscription must not be required merely to access the user's own original file or preserve their project. Show quality options and estimated resource use before a costly render.

## 6. Subscription, daily and monthly allowances

Keep these controls distinct:
1. Plan entitlements: which workshops and advanced features are available.
2. Daily allowance: regularly replenished capacity for day-to-day creation.
3. Monthly allowance: a separate period-based package for broader use.
4. Purchased/promotional credits: separately identified grants with explicit expiry/rollover terms.
5. Hard resource limits: duration, resolution, file size, concurrent jobs, storage and request frequency.
6. Provider-cost protection: platform-wide spend ceilings and abuse controls, independent of user balances.

Show each balance, what it can be spent on, and its exact next refresh time. The order of consumption, rollover, expiry, time zone, reset time, and whether unused daily/monthly credits accumulate are product decisions that must be documented before implementation. Do not silently assume or copy another platform's rules.

Before a credit-consuming generation/render, show an estimate and request confirmation where appropriate. Reserve credits server-side before provider use; settle from trusted measured usage; release unused reservations only after a confirmed outcome. A timeout or unknown provider outcome must be reconciled, not blindly refunded or double-charged.

Never invent credit amounts, plan prices, daily/monthly allocations or generation costs. Measure provider, storage, rendering, bandwidth and operational costs first.

## 7. Authorship, ownership and commercial rights

Keep separate:
- User-provided inputs and source files.
- Human-authored lyrics, scripts, images, recordings and other contributions.
- AI-generated output and rights the platform/provider can contractually grant.
- Third-party model, dataset, codec, font, stock-media and provider license restrictions.
- Permission to publish in ПУЛЬС.
- Permission to use a work commercially.
- Legal copyright protection/registrability in the applicable jurisdiction.

A paid plan may include broader commercial-use permissions only where the relevant provider agreement allows them and PWA Studio can grant them. Never promise that every AI-generated output is automatically copyright-protected or exclusively owned. Explain rights for works made during an active subscription, after cancellation, and under a free tier; obtain legal review before launch.

Projects and outputs are private by default. Publishing to ПУЛЬС is optional and separate from downloading, using or retaining one's own work. Unpublishing removes public discovery/access while preserving the owner's private source/project unless the owner explicitly deletes it.

## 8. ПУЛЬС — community and publication

Target capabilities:
- Voluntary gallery aggregating public works from all creative branches.
- Sections such as New, Trending, Popular, Music, Cinema, Video, Images and Creators.
- Creator pages with published works and free follow controls; following is distinct from a paid plan.
- Likes, comments, notifications for reactions/new followers, with user preferences.
- Optional community chat and, later, private messages.
- Reporting, blocking, comment controls, moderation, appeals and anti-spam protections.

Privacy/safety: private by default; explicit action for publication; clear visibility scope; author can unpublish, delete, disable comments and manage blocks. Only public/authorized assets may be served to other users. Never expose private bucket paths or long-lived signed URLs. Enforce permissions and moderation server-side.

## 9. Recommended implementation order

1. Read-only audit of live Supabase schema, migration ledger, RLS, grants, Storage buckets/policies and deployment configuration. Resolve duplicate migration-version 0005 source conflict before any related SQL change.
2. Verify account isolation, admin authorization, AI Companion history, project persistence, restore and cross-device behavior.
3. Implement private media upload and canonical asset metadata; test owner-only access and deletion.
4. Complete Audio Studio capture/import/playback/export using private user-owned assets.
5. Build shared audio/video players and tested MP3/MP4 export paths; document exact codec/container support.
6. Connect one provider workflow at a time (image, voice, music, video) with async jobs, cancellation, retries, safety, measured usage and cost reconciliation.
7. Approve subscription entitlements, daily/monthly allowance behavior, pricing, rollover/expiry, quality tiers and rights language only after measured economics and legal review.
8. Implement ПУЛЬС publication/privacy foundations, creator profiles, follows, likes/comments, notifications and moderation.
9. Run mobile end-to-end, second-account isolation, load/security and backup/restore tests before public launch.

## 10. Explicit safety boundary

This inventory is documentation only. It does not authorize merging a draft pull request, deploying to production, applying SQL migrations, changing live Supabase schema/RLS/grants/buckets/policies, enabling billing or real credit deductions, purchasing credits, launching paid generation jobs, or publishing user works. Those actions require a separate explicit confirmation after their exact impact is reviewed.
