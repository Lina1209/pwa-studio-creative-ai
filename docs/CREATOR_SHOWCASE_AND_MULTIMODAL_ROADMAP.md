# PWA Studio — creator showcase and multimodal product roadmap

Last reviewed: 2026-11-23

This document expands the product plan with an inspiration area, an opt-in creator gallery and a complete audio / speech / voice / video capability map. It does not imply that any unconnected provider or feature is already available.

## 1. Product surfaces: examples, showcase and marketplace are different things

### A. Inspiration and examples page

A public page available to guests, with platform-curated examples that teach people what PWA Studio can do:

- short demo films and scene sequences;
- image and style examples;
- prompt examples with explanations;
- storyboard and character-bible examples;
- voiceover, music and sound-effect examples;
- editing, subtitle and dubbing examples;
- starter project templates.

Each example should explain the workflow and identify which parts are real, demo, generated or manually edited. A button such as “Use this example” creates a copy in the user's workspace; it never edits the original.

### B. Creator Showcase / Gallery of Works

A separate opt-in gallery of user-published creations. The default state of every project, image, video, audio file, voice sample, prompt and character is **private**.

A user explicitly chooses:
- publish this item or keep it private;
- display name / creator attribution;
- title, description, category and tags;
- whether to show the prompt and generation settings;
- whether viewers may save, remix or use it as a template;
- a clear publication license and any provider-specific restrictions.

Recommended initial categories:
- Films and video clips
- Images and visual art
- Music and sound design
- Voiceover and narration
- Scripts and storyboards
- Prompts and reusable templates

Gallery functions:
- search, filters, sorting and curated collections;
- creator profiles and portfolios, only with opt-in;
- likes, bookmarks and personal collections;
- detail page with preview, attribution, creation metadata and license;
- “Remix” or “Use as template” only where the creator explicitly enabled it;
- report content, withdraw publication and request takedown;
- staff curation and featured examples.

Do not make private Storage buckets public. Publish a controlled preview/derivative and metadata record; serve media through a dedicated public-publication path with moderation, access and takedown controls. Keep the source asset private where possible.

### C. Marketplace — later, not MVP

A marketplace is not just a gallery. It introduces payments, creator identity checks, licensing, royalties, disputes, refunds, tax and fraud operations. Defer it until the core studio, moderation, rights, billing and creator support are proven.

Start with a free showcase and reusable templates. If monetization is later introduced, make the license, price, permitted use, creator payout and platform fee explicit before purchase.

## 2. Publication, rights and safety rules

- Nothing becomes public through a default toggle or because a user generated it.
- The creator must confirm they have rights to the source media and permission for recognizable real-person likenesses and voices.
- A public gallery display license should be narrow: permission to host and display the selected work. Remix/template permissions must be separate, optional and revocable for future uses.
- Existing downloads and copies cannot always be recalled; explain this before publishing.
- Record creator, publication timestamp, selected license/version, provider/model, generation job and asset provenance where available.
- Strip EXIF/GPS and other unnecessary metadata from published images and previews.
- Do not publish private prompts, source files, project names, voice samples or identity information without separate consent.
- Voice libraries must not accept unauthorized voice clones. Require verification and evidence appropriate to the voice rights model; support takedown and revocation.
- Every published item needs report, review, unpublish and appeal paths.
- Keep private user work inaccessible to gallery moderators unless the user submits it or a lawful, documented safety process requires access.
- Provide age-appropriate controls and a content rating/visibility policy before public user uploads are enabled.

## 3. Reusable creator assets

A strong studio should let people reuse their own building blocks without exposing them publicly:

- prompt collections and prompt variables;
- character bibles, approved reference images and continuity notes;
- scene/storyboard templates;
- brand/style kits and color/font presets;
- voice profiles and pronunciation dictionaries;
- sound-effect and music collections;
- editing presets, subtitle styles and export profiles.

A “duplicate into my workspace” action must create a new owner-scoped copy and preserve the source attribution/license. Never share a private asset merely because it is referenced by a public project.

## 4. Audio, speech and voice roadmap

The current Audio Studio is a local microphone recorder and file preview. It does not yet upload audio or call speech/music providers.

### Audio foundation

1. Secure upload and recording to private storage.
2. Audio asset metadata: owner, duration, codec, sample rate, channels, file size, checksum, provenance and retention.
3. Playback, waveform, trim, split, volume, fade, mute and basic mixing.
4. Export to supported audio formats with verified playback.
5. Job status, cancellation, retries, usage metering, quotas and cost visibility.

### Speech and narration

- Text-to-speech for narration and character dialogue.
- Multiple languages and voices, including Russian, Kazakh and English where a provider supports them.
- Pronunciation dictionary, pauses, emphasis, speed, pitch and emotion controls where supported.
- Speech-to-text transcription with editable transcript and timestamps.
- Automatic subtitles/captions with manual correction.
- Translation and dubbing workflows that preserve timing where possible.
- Voiceover generation per scene and reusable voice assignments.
- Audio cleanup, noise reduction and loudness normalization where provider/tooling permits.

### Music and sound design

- Prompt-based music generation and instrumental beds.
- Sound-effect generation from text and optional timing reference.
- Ambience, Foley and transition effects.
- Music/SFX libraries with license and usage metadata.
- Timeline mixing, ducking, fades and per-track volume.
- Explicit controls for commercial-use rights and provider restrictions.

### Voice design and cloning are not the same

- **Voice design:** create or select a synthetic voice from supported parameters; it is not a copy of a real person's identity.
- **Voice cloning:** reproduce a specific speaker. This must be a separately gated, high-risk feature with explicit speaker authorization, appropriate verification, private sample storage, limited permissions, audit trail, revocation/deletion and abuse response.
- A user must not be able to publish another person's voice or a cloned voice without documented permission.
- Do not imply voice cloning or a public voice marketplace exists until the complete provider and consent workflow has passed testing.

## 5. Image and video creation roadmap

### Image capabilities

- Text-to-image and image editing where a concrete provider is approved.
- Reference-image guidance, reusable style presets and character consistency.
- Variants, seed/settings reuse and generation history.
- Safe upload, image metadata, private previews and provenance.

### Video capabilities

- Text-to-video, image-to-video and reference-guided video where supported by the selected provider.
- Scene-by-scene generation, multiple takes and regeneration of one scene without destroying the rest of a film.
- Storyboard-to-shot workflow with camera, motion, duration, aspect ratio and resolution settings.
- Character continuity and reference assets across scenes.
- Video-to-video or extension only where provider APIs support it.
- Voice, music, ambience, sound effects and subtitles linked to scene/timeline assets.
- Timeline editing: tracks, trim, split, reorder, transitions, titles, captions, audio mixing and preview.
- Render queue with progress, cancel/retry, resume/recovery and estimated/actual cost.
- Export a real MP4 or other verified format, with codec, dimensions, duration, audio/video sync and download integrity checks.

A planning sheet, storyboard or generated clip is not a finished film. The UI must distinguish plan, generated asset, assembled preview and verified final export.

### Provider-neutral architecture

Use the existing generation-job, outbox, provider-operation journal, worker and private-storage foundations. A provider adapter must document:
- exact API/model/version and region;
- input/output formats and limits;
- create/status/cancel behavior;
- idempotency and lookup guarantees;
- moderation and safety behavior;
- pricing, metering, failure and cancellation billing;
- retention, deletion and output license;
- latency, availability and retry policy.

The repository's 2026-11-23 provider idempotency audit marks production video generation as blocked: no concrete production video-provider adapter exists in the current tree. Do not enable a video model or promise a render until the adapter contract and real provider-account test are complete.

## 6. Inspiration from established products

The patterns below are useful references, not a mandate to copy a giant platform's full complexity:

- **Adobe Firefly:** its Community Gallery surfaces selected images and videos, shows creator/prompt context, supports likes and remixing into the editor. Its current Firefly editing workflow also connects generated video and sound effects to a timeline.
- **Runway:** generations and uploaded assets are private by default; users explicitly share into projects, where project members can collaborate. This is a strong privacy default for PWA Studio.
- **ElevenLabs:** its Voice Library has curated collections, search and filters. Public sharing is limited to verified Professional Voice Clones; synthetic Voice Design and Instant Clones are not freely publishable. This is a useful consent and rights precedent.
- **Canva:** template links let users create their own editable copy, and the Creator program separates the template marketplace from ordinary design sharing.
- **OpenAI Projects:** related chats, files and project instructions are kept together so work can continue across devices. PWA Studio should apply the same project-context principle to films, characters, prompts and assets, with strict owner isolation.

Official references:
- Adobe Firefly Community Gallery: https://helpx.adobe.com/uk/firefly/web/share-and-download/share-in-the-firefly-community-gallery/firefly-community-overview.html
- Adobe Firefly generation and editing: https://helpx.adobe.com/firefly/web/unified-generation-and-editing-experience/generate-and-edit-content.html
- Adobe Firefly timeline sound effects: https://helpx.adobe.com/firefly/web/firefly-video-editor/generate-audio/generate-sound-effects.html
- Runway Projects: https://help.runwayml.com/hc/en-us/articles/52474899121555-Introduction-to-Projects
- Runway asset privacy: https://help.runwayml.com/hc/en-us/articles/4408611980563-Managing-assets
- ElevenLabs Voice Library: https://elevenlabs.io/docs/help-center/product/voices/voice-library/what-is-the-voice-library
- ElevenLabs voice-sharing rules: https://elevenlabs.io/docs/help-center/product/voices/voice-library/can-i-share-an-ai-generated-voice-in-the-voice-library
- Canva template links: https://www.canva.com/help/share-template-link/
- Canva Creator marketplace: https://www.canva.com/creators/templates/
- OpenAI Projects: https://help.openai.com/en/articles/10169521-projects

## 7. Recommended delivery order

1. Complete and verify private media upload and owner-scoped asset metadata.
2. Finish Audio Studio upload, playback and export foundation.
3. Add speech-to-text, subtitles and text-to-speech using a provider-neutral job contract.
4. Add music/SFX and basic multitrack mixing after costs and licenses are known.
5. Complete a real image-provider adapter and production worker deployment.
6. Add a real video-provider adapter only after idempotency, pricing, safety, region and rights review.
7. Build timeline assembly and verified video export.
8. Publish platform-owned demo examples and starter templates.
9. Add opt-in creator showcase after moderation, takedown, licensing and privacy controls.
10. Consider public voice library or marketplace only after identity, consent, creator rights and payment systems are mature.

## 8. Cross-cutting capabilities not to forget

These capabilities improve the whole studio and should be planned alongside the media modules:

- **Project collaboration (later):** invite-only project spaces, owner/editor/commenter roles, review-only links with expiry, comments pinned to scenes or timeline timecodes, version history and clear ownership. Shared projects must be explicit; private-by-default remains the baseline.
- **Prompt and workflow templates:** reusable prompt variables, prompt versions, style presets, storyboard templates, character bibles, export presets and starter projects. “Use template” must copy rather than mutate the original.
- **Generation review:** compare variants side by side, mark favorites, rerun one scene, reuse settings, show the provider/model and cost estimate before generation, and preserve a clear job history.
- **Exports and portability:** video MP4, audio WAV/MP3 where supported, subtitles SRT/VTT, still images PNG/JPEG/WebP, and a documented editable-project backup/export format. Validate actual codecs and file integrity rather than promising every format.
- **Accessibility:** keyboard navigation, visible focus, screen-reader labels, reduced-motion support, captions, transcripts and accessible playback controls.
- **Localization:** Russian, Kazakh and English UI and help content; generation language support must be shown per provider rather than assumed.
- **Help centre and service status:** searchable guides, known issues, release notes, planned maintenance and an incident/status page. This reduces repetitive support tickets and gives users a trustworthy place to check outages.
- **Quality feedback:** allow a user to rate a generation or report a failed job, but keep that separate from public likes and never publish private prompts or source material as part of a feedback event.
- **Human-reviewed support AI:** later, an internal assistant may summarize a ticket, translate it or draft a reply. It must never send automatically, decide sanctions, expose AI Companion history or use support content with an external model without clear disclosure and an approved data flow.

## 9. Acceptance criteria

- All user projects and generated assets remain private until an explicit publication action.
- Publishing one item does not publish the whole project or linked private assets.
- Remix creates a new copy and preserves attribution/license.
- User can unpublish and request takedown; reports enter a moderated queue.
- Public media previews contain no unnecessary EXIF/GPS metadata.
- Audio uploads and exports are verified, owner-scoped and quota-metered.
- Transcripts and captions are editable and tied to source timestamps.
- Voice cloning requires documented consent and can be revoked/deleted.
- Video output is not called complete until a real playable file passes integrity checks.
- All generation operations use provider contracts, durable job status, idempotency rules and usage accounting.
