# PWA Studio Capability Catalog

Status: product capability map; this document describes the verified product surface and the intended creative workflows. It does not claim that every studio is connected to a generation provider.

## Product principle

Users start with a creative intention — for example, "make a short film about this character" — not with a technical operation code. PWA Studio should guide the user through the right studios, preserve project context and assets, and coordinate child operations behind one understandable workflow.

The shared platform is the trunk of the creative tree: identity, projects, asset library, Prompt Studio, AI Companion, safety, and orchestration. Creative studios are branches. A finished work may combine outputs from several branches.

## Readiness vocabulary

- **Implemented UI** — a corresponding page, navigation area, or local interaction is present in the repository.
- **Partially implemented** — some workflow or local draft behavior exists, but important persistence, provider, or export steps are not verified or connected.
- **Planned** — a product capability or integration is described as a future step, not a working feature.
- **Backend available; deployment/config required** — an API path exists in source, but use depends on deployed backend, valid credentials, and provider configuration.
- **Not verified** — the repository evidence available for this catalog is insufficient to claim implementation.

A visible navigation item is not proof of a working provider integration. A design entry is not proof of production availability.

## Shared platform capabilities

| User-facing capability | Product area | Operation code(s) | Inputs | Expected outputs | Dependencies | Readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Create an account / sign in / request password reset | Account | — | Email and authentication credentials | Authenticated session | Supabase Auth configuration | Implemented UI and auth integration in source; live environment still requires verification |
| Start and manage a creative project | Projects / Mini Movie Studio | `ai_companion.workflow` only when orchestration is later added; project CRUD is not a billable AI operation | Project title, description, local draft data | Project draft and version history | Browser storage; future verified cloud persistence | Partially implemented: local drafts, edit/copy/delete and local version history exist; cloud sync awaits live migration and second-device verification |
| Ask the built-in creative assistant | AI Companion | `ai_companion.chat` | User message and conversation context | Assistant response | Deployed FastAPI backend, Supabase session, configured AI provider | Backend endpoint available; deployment/configuration required |
| Create, improve, translate, or adapt prompts | Prompt Studio | `prompt.create`, `prompt.rewrite`, `prompt.translate`, `prompt.adapt` | Idea or existing prompt, language, target model/modality | Reusable prompt text | Deployed FastAPI backend and configured provider | UI and backend prompt endpoint exist in source; deployment/configuration required |
| Browse and reuse project media | Media Library | `asset.store`, `asset.read`, `asset.delete`, `asset.export` | Uploaded or generated asset | Organized, reusable asset | Private Storage, upload UI, access policies | Planned/partial: media-library area exists, but README states media upload UI is not implemented; live Storage is unverified |
| Follow product guidance and safety rules | Guide / Rules | — | User questions and policy content | Guidance and safety information | Maintained documentation | Implemented UI area; content review remains part of release readiness |

## Creative branches

| User goal | Studio / branch | Operation code(s) | Required inputs | Expected output | Dependencies and hand-offs | Readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Turn an idea into a story and scene plan | Mini Movie Studio — story and scenes | `ai_companion.workflow` for a future orchestrated assistant flow; `prompt.create` where Prompt Studio is explicitly used | Idea, genre, duration, tone, characters | Story draft, scene breakdown, production notes | AI script generation, structured project persistence | Partially implemented: local project stages and editable production notes/text exist; AI screenwriter and generated storyboard are not connected |
| Plan characters, voices, and a film workflow | Mini Movie Studio — production planning | `voice.generate` only when a real voice-generation task is invoked later | Character descriptions, casting notes, scene context | Character and voice plan | Character Library, consent controls, voice provider | Partially implemented as local planning stages; generation and Character Library are planned |
| Generate an image | Image Studio | `image.generate` | Prompt, style, dimensions, output count | Image asset(s) | Approved image provider, job lifecycle, asset storage | Planned; provider integration is not verified |
| Edit or upscale an image | Image Studio | `image.edit`, `image.upscale` | Source image, edit instruction or target scale | Edited/upscaled image asset | Image provider and source-asset access | Planned; provider integration is not verified |
| Generate or extend a video clip | Video / Mini Cinema | `video.generate`, `video.extend` | Prompt or source clip, duration, aspect ratio and other supported settings | Video clip | Video provider, async job tracking, storage and moderation | Planned; README explicitly says video generation is not connected |
| Transform or AI-edit a clip | Video / Mini Cinema | `video.edit` | Source clip and edit instruction | Transformed clip | Video provider and media pipeline | Planned; provider integration is not verified |
| Assemble a timeline and render a film | Video Editor / Mini Cinema | `video.render`, `video.export` | Scenes, clips, images, audio, timeline settings | Rendered film and export file | Timeline editor, render workers, storage and export pipeline | Planned; timeline editor and MP4 rendering are not connected |
| Generate a song or music bed | Music Studio | `music.generate`, `music.extend`, `music.remix` | Musical brief, mood, lyrics or reference where permitted | Audio track / variants | Music provider, rights checks, audio storage | Planned; no connected generation provider is verified |
| Generate narration or character speech | Voice Studio | `voice.generate`, `voice.clone`, `voice.convert` | Text, authorized voice selection or eligible voice sample | Speech audio | Voice provider, explicit consent, identity and abuse safeguards | Partially represented by a voice-workshop UI area; cloning and generation are not connected |
| Transcribe speech | Voice / Audio Studio | `voice.transcribe` | Audio file | Transcript and measured audio duration | Speech-to-text provider and audio access | Planned; provider integration is not verified |
| Process audio | Audio Studio | `audio.process` | Audio asset and processing settings | Processed audio asset | Audio worker/provider and storage | Planned; provider integration is not verified |

## Cross-branch creative journeys

These are target journeys. They describe how the product should orchestrate studios; they are not claims that the full journeys work today.

### 1. Idea → short film

1. User describes the idea to AI Companion.
2. Prompt Studio helps shape prompts and creative direction.
3. Mini Movie Studio turns the idea into a story, characters, and scene plan.
4. Image Studio creates visual references and scene assets.
5. Video branch generates clips for selected scenes.
6. Voice and Music branches add narration, dialogue, and soundtrack.
7. Video Editor assembles, renders, and exports the film.
8. Media Library stores reusable source assets and the final output.

### 2. Character → voice → film

1. Define a character in the project.
2. Create a visual reference in Image Studio.
3. Select or generate a voice only with appropriate authorization and consent.
4. Reuse the character and voice references across scenes.
5. Send scene-level visual, video, and audio tasks to their respective studios.
6. Keep the character identity and approved assets linked to the project.

### 3. Song → music video

1. Develop the musical brief and create a track in Music Studio.
2. Create a visual concept and storyboard in Mini Movie Studio.
3. Generate image references and video scenes.
4. Align scenes to the music in the editor.
5. Render and export the completed clip.

### 4. Image → animation

1. Select an image from the project or Media Library.
2. Submit it with a motion instruction to the video/animation workflow.
3. Track the generation job and its attempts.
4. Save the resulting clip as a new asset while preserving the original image.

## Orchestration contract

- One user-facing journey may create a parent workflow and multiple child operations.
- Every child operation belongs to a studio branch and uses a stable operation code from `PWA_STUDIO_OPERATION_REGISTRY.md`.
- Parent workflows must not duplicate child provider or infrastructure costs.
- Keep the source project, prompts, scene references, assets, and output relationships explicit.
- A retry is a new attempt under the same logical operation; do not silently create duplicate billable work.
- Do not treat unknown usage as zero. Record measured dimensions only.
- Never expose provider keys, private prompts, raw media, or sensitive voice samples in telemetry.
- Voice cloning or use of a person's likeness requires clear authorization, consent, and safeguards.
- The catalog does not define prices, quotas, credit costs, or payment behavior.

## User experience rules

1. Lead with outcomes ("Create a film", "Make a song", "Animate an image"), not internal API names.
2. Let the user begin in any branch and discover relevant companion tools without losing project context.
3. Keep one project identity and a shared asset relationship model across branches.
4. Explain unavailable integrations honestly and preserve work as drafts where possible.
5. Make hand-offs visible: what will be created, which studio will do it, what input is needed, and where the result will appear.
6. Let users review and approve consequential actions before provider calls, publication, sharing, or any future charge.

## Readiness and release gates

Before describing a capability as fully available:
- verify its UI in the deployed frontend;
- verify its backend endpoint and provider adapter, if applicable;
- verify authentication, authorization, consent, moderation, and rate limits;
- verify job status, retries, cancellation, and ambiguous outcomes for asynchronous work;
- verify asset persistence and access controls;
- verify measured usage and cost evidence before introducing quotas or pricing;
- test the complete user journey on a second device where cloud synchronization is involved.

## Source-of-truth note

This catalog is based on the repository README and the design-only operation registry. It deliberately distinguishes visible UI, local draft behavior, backend endpoints, and future provider integrations. Revisit the readiness labels whenever implementation or deployment changes.
