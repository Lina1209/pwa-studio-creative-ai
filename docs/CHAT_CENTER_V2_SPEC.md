# PWA Studio — Chat Center v2

Status: product/engineering specification. This document does not claim that direct messaging, uploads, push notifications or moderation controls are already deployed.

## Product direction

Replace the support-only floating dialog as the primary destination with a small, persistent entry point labelled **«Сообщения»**. It should look like a calm, compact glass panel/button with an unread badge and one short status line (for example, «Есть новое сообщение»). Clicking it navigates to a dedicated full-page **Chat Center** at `/messages` (or the app's equivalent view route); it must not trap the user in a tiny popup.

The floating launcher remains a shortcut, not the chat itself. On mobile it must respect safe-area insets and never cover the main composer/action controls.

## Chat Center information architecture

- **Диалоги** — private one-to-one conversations between users, plus the official **Команда PWA Studio** conversation.
- **Поддержка** — private support requests with categories, ticket number and lifecycle. Keep this separate from personal DMs and AI Companion history.
- **Уведомления** — unread messages, admin replies, moderation decisions, security notices and account events.
- Conversation list: avatar/initials, display name, last message preview, time, unread badge, pinned state and online/last-seen only if the user explicitly enables presence.
- Conversation screen: clear recipient header, chronological message stream, date separators, reply composer, attachment previews, send state, and a compact conversation menu.
- Empty state: explain how to contact the team and how to start a conversation; do not show fabricated demo messages.

## Message composer

A compact, editor-like composer with:
- multiline text input, send button and Enter/Shift+Enter behavior;
- emoji picker with search and accessible labels;
- sticker picker using a curated, licensed first-party sticker pack (custom uploads can come later);
- attachment button for images and files, with preview, remove-before-send, upload progress and retry;
- drag/drop and paste image support on desktop where safe;
- image thumbnails with a click-to-view lightbox; other files shown as safe downloadable cards;
- clear limits and accepted formats before upload.

Do not render user message HTML. Store plain text plus structured attachment metadata. Escape text and validate all uploaded content on the server. Use private object storage, short-lived signed download URLs, MIME sniffing, file size/count limits, malware scanning where available, and reject executable/script formats. Strip image metadata where practical. Never expose storage service credentials in the browser.

## User-to-admin contact and notifications

Every authenticated account gets an official **Команда PWA Studio** thread (or a support entry that opens the same dedicated conversation view). A user can start a conversation from their personal account without hunting for a separate form.

When a new user message arrives:
1. create an in-app admin notification with unread count;
2. show it in the admin inbox and notification center;
3. optionally send a transactional email after provider configuration and delivery tests;
4. add push notifications only after subscription, permission, unsubscribe and delivery lifecycle are implemented.

Suggested notification copy: **«Новое сообщение в PWA Studio»** with a link to the authenticated conversation. Keep message text out of lock-screen previews by default. Do not claim instant delivery or an SLA until verified.

Admin notifications need deduplication, read/unread state, delivery status, retry policy and user preference controls. A failed email must not lose the in-app notification.

## Admin moderation console

A role-protected moderation/helpdesk workspace with:
- search by user ID/display name, conversation ID and ticket number (with privacy-scoped results);
- filters: unread, reported, active, muted, banned, support, priority;
- view report reason and only the conversation context needed to investigate;
- hide/remove a message, restore it when appropriate, or mark it as reviewed;
- edit only for narrowly defined corrections (for example, removal of exposed personal data); preserve the original content in a restricted audit record and show a visible “изменено модератором” marker to participants;
- warn, mute for a defined period, suspend messaging, or ban an account for a defined period/permanently;
- every sanction requires a reason, actor, scope, start/end time, and an appeal/review path;
- unban/restore access and record the decision;
- pin/close official support conversations and change category/status;
- internal notes are separate from user-visible messages and are never returned by user APIs.

Do not silently rewrite a user's words. Prefer hide/redact plus a visible moderation marker. Permanent bans and actions affecting account access should require a high-privilege capability and explicit confirmation. All privileged reads and mutations must be audited.

## Privacy and abuse prevention

- Private DMs are visible only to their participants and authorized moderation roles under a documented, audited policy.
- Do not give every admin unrestricted access by default. Use least-privilege capabilities and log access to private conversations.
- Users can block another user, report a message/conversation and control who may message them (everyone / nobody / selected groups, if groups are later introduced).
- New accounts receive rate limits and anti-spam protections; enforce limits server-side.
- Add abuse reporting, attachment reporting, repeat-offender controls, appeal workflow and retention/deletion rules.
- Do not expose reporter identity to the reported user.
- Clear cached conversation content and selected conversation state on sign-out/account switch.
- Do not merge DMs, support conversations, public community posts or AI Companion history into one table or permission scope.

## Data model and API work

Build on the existing private support inbox, but do not overload ticket tables into a generic chat database.

Suggested entities:
- `conversations` (type: direct/support; participants; last_message_at; created_at);
- `conversation_participants` (user_id; role; last_read_at; notification preferences);
- `messages` (conversation_id; sender_id; body_text; created_at; edited_at; deleted_at; moderation_state);
- `message_attachments` (private storage key; safe filename; detected MIME; size; scan status);
- `message_reports` (reporter; message/conversation; reason; status);
- `user_messaging_restrictions` (mute/ban scope, reason, starts_at, expires_at);
- `moderation_events` (append-only audit history; actor; action; reason; target; before/after metadata);
- `user_notifications` (recipient; kind; target; read_at; delivery state).

All membership, block, rate-limit and moderation checks must happen server-side for every read/write. Use transactional RPCs for conversation creation + first message, message append + conversation activity, and sanction changes. Add idempotency keys before client retry is enabled.

## Delivery phases

1. **Chat Center shell:** dedicated page/view, compact launcher, conversation list/detail layout, responsive design, reuse existing support APIs for the official support conversation.
2. **Notifications:** unread counts, in-app admin alerts, notification center and safe polling/realtime after auth testing.
3. **Direct messages:** participant-scoped conversations, start conversation, block/report and server-side anti-spam.
4. **Rich composer:** emoji and curated stickers first; then private image/file attachments with scanning and signed URLs.
5. **Moderation:** role/capability matrix, audited hide/redact, warning/mute/ban/unban, appeals and review queue.
6. **Email/push:** only after provider configuration, consent/preferences and end-to-end delivery verification.

## Release gates

- User A cannot list, read, search, infer or mutate User B's conversations or attachments.
- A blocked or banned account cannot bypass restrictions through alternate endpoints.
- Non-moderators cannot use admin moderation APIs, regardless of UI state.
- Admin actions are reasoned, auditable and reversible where appropriate.
- Original content is preserved in restricted audit records when moderator edits/redacts.
- Attachments are private, validated, size-limited and malware-scanned before download.
- Account switching/sign-out clears all cached private conversation data.
- Android Chrome and desktop keyboard/screen-reader flows pass.
- Notification delivery failure never drops the underlying message or in-app notification.
- No feature is described as live until its database migration, backend, frontend and production verification are complete.
