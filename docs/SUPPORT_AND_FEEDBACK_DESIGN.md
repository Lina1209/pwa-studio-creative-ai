# PWA Studio — Support, feedback and customer conversation design

Last reviewed: 2026-11-23

Status labels in this document are evidence-based. Code on a review branch is not production deployment; migrations are not live until applied and verified.

## 1. Three different conversations — keep them separate

PWA Studio needs three distinct communication surfaces:

1. **AI Companion** — a private conversation with the AI assistant. It is not a support ticket and is never visible to administrators by default.
2. **Support and feedback inbox** — a private, asynchronous conversation between one user and the PWA Studio team. It is the user's route for account help, bug reports, billing questions, feedback and feature requests.
3. **Community chat and public idea board** — public or semi-public user-to-user spaces. These require a separate moderation system and must not be used for confidential support.

Do not merge their message tables, permissions, retention rules or UI state.

## 2. Existing implementation found in the review branch

The current review branch already contains a first support-inbox implementation:

- Migration 0055_private_support_inbox.sql defines private support_tickets and support_ticket_messages tables. Direct browser access is revoked; the API mediates access using the server-side service role.
- FastAPI routes let a signed-in user create a ticket, list their own tickets, read their own conversation and reply.
- Owner-only routes expose the admin queue, read a ticket, reply and change its status.
- The frontend contains a floating support launcher and native dialog widget with categorized request form, optional page-only diagnostic context, the user's ticket list and conversation view; the owner-only inbox remains in the account dashboard.
- Permission checks use the named capabilities admin.support.read, admin.support.reply and admin.support.status.manage; administrative reads and mutations are audited.
- Migration 0091_support_inbox_atomic_mutations_and_categories.sql adds request categories and optional diagnostic context, and moves ticket creation/message append into database transactions.

**Deployment boundary:** this code is in the open Draft PR/review branch. It has not been merged or deployed by this work session. Migrations 0055 and 0091 have not been applied to the live Supabase project. The CI suite must pass after the latest commits; that is separate from live browser, account-isolation and database verification.

### Important defects addressed in this branch

The previous service made two independent REST writes when creating a ticket (ticket first, initial message second). A failure between them could leave an empty ticket. Replies also inserted a message and updated the ticket status in a second request, so partial completion was possible.

The old status mapping was inverted: a user reply moved the ticket to waiting_user, while an administrator reply moved it to in_progress. Migration 0091 introduces atomic RPCs and corrects the intended lifecycle:

- initial user submission → open;
- team takes ownership → in_progress;
- administrator replies → waiting_user;
- user replies → open;
- team marks the request complete → resolved;
- team closes the request → closed.

User replies to resolved/closed tickets are rejected; a user can start a new request. The first administrator response timestamp is recorded.

## 3. User experience

### Entry point

Add a small, fixed **“Помощь и обратная связь”** launcher in the bottom corner on desktop and mobile. It should be keyboard accessible, screen-reader labelled, dismissible, respect safe-area insets and never cover the main action buttons.

The supplied Miror/Forumotion snippet was used as a visual reference for a compact, resizable chat panel. PWA Studio now uses a native dialog widget connected to its own support API; the forum snippet itself must not be pasted into PWA Studio as-is:

- insertChatBox(...), {U_FRAME_CHATBOX} and resizeElement(...) are Forumotion-specific template/runtime hooks;
- the placeholder URL and JavaScript helper do not exist in this Vanilla JS application;
- an external forum iframe would create a separate identity, privacy, moderation and availability boundary.

Keep the native PWA Studio dialog component connected to the existing authenticated support API. The widget is an entry point to a persistent support conversation, not a second independent chat backend. The current implementation is asynchronous and uses explicit refresh; it is not a realtime chat service.

### New request form

Collect only what is useful:

- category: general question, bug/technical issue, account/access, billing/credits, feature request, product feedback, safety/privacy;
- short subject;
- message body;
- optional, unchecked-by-default diagnostic context;
- later: optional attachment upload through private storage.

Diagnostic context must be explicitly selected. Start with a small allowlist such as current application section, app version, a user-selected project/job reference and a non-sensitive error code. Never silently attach prompts, conversation history, project contents, tokens, email addresses, IP addresses, browser fingerprints or private media.

Do not require a user to expose a private project just to ask for help. If an attachment is introduced, show exactly what will be sent and allow removal before submission.

### User conversation view

Show:

- ticket number and subject;
- category and current status;
- chronological messages with clear “Вы” / “Команда PWA Studio” labels;
- sent time and delivery/error state;
- reply composer while the ticket is open;
- a clear resolved/closed state;
- refresh and notification indicators.

For the first release, this is **asynchronous support chat**, not guaranteed real-time messaging. Use safe polling or explicit refresh until an authenticated Realtime/WebSocket channel is separately designed and tested. Never label it “online now” or imply instant replies without a real service-level commitment.

### Notifications

Recommended sequence:

1. In-app unread indicator and ticket status updates.
2. Transactional email when the team replies or a ticket changes state, subject to verified email configuration and user notification preferences.
3. Optional push notifications only after PWA push permission, subscription lifecycle, unsubscribe and delivery reliability are implemented.

Do not put sensitive message contents in push previews by default. A notification should link back to the authenticated ticket.

## 4. Owner/admin inbox

The owner inbox should become a compact helpdesk, not a general public chat room.

### Queue capabilities

- Filter by status and category.
- Search by ticket ID and subject; avoid broad searches over private message content until access and retention are reviewed.
- Sort by newest activity and oldest unanswered request.
- Show unread/new count and time since last user message.
- Add priority and assignment when multiple support staff exist.
- Display first-response and resolution-time metrics.
- Keep a visible audit/event history for privileged actions.

### Conversation actions

- reply to the user;
- add an internal note that is never returned by user-facing APIs;
- assign/unassign a support teammate when staff roles exist;
- set priority and category;
- move through open / in progress / waiting for user / resolved / closed;
- reopen with an explicit reason;
- use reviewed canned replies for repeated questions;
- link a bug report to an internal issue without exposing internal notes.

Never use the same message type for internal notes and public replies. Never rely on frontend visibility to protect internal content.

### Service operations

Before adding multiple agents, introduce:
- role separation between owner, support agent and moderator;
- least-privilege capabilities for reading/replying/changing status;
- assignment history and immutable audit events;
- two-person approval for sensitive account or financial actions;
- configurable service hours and response targets;
- escalation for security, privacy, payment and safety cases.

Do not promise a response-time SLA until staffing and availability are known.

## 5. Categories and routing

| Category | Intended handling |
| --- | --- |
| General question | Help centre / saved answer, then team |
| Bug / technical issue | Collect optional page, app version, error code and job reference; link to internal bug |
| Account / access | Verify account ownership; never request passwords or authentication codes |
| Billing / credits | Read-only support first; financial changes use the separate audited finance-request workflow |
| Feature request | Product feedback queue; no promise that a feature will be built |
| Product feedback | Private feedback initially; public display requires a separate opt-in |
| Safety / privacy | Restricted access, priority escalation and documented handling |

A content-abuse report should eventually use a dedicated moderation-report workflow, not ordinary support tickets. Do not reveal reporter identity to the reported user.

## 6. Data model and security

Current base tables are support_tickets and support_ticket_messages. Migration 0091 adds category, bounded JSON context, first_response_at, resolved_at and closed_at.

Future additions, only when needed:
- priority, assigned_to, tags;
- support_ticket_events for assignment, category, priority and status transitions;
- support_ticket_internal_notes or a message visibility field protected from customer APIs;
- attachment metadata referencing private Storage objects;
- user satisfaction rating and optional comment after resolution;
- notification delivery records and user preferences.

Security requirements:
- authenticated users may only access tickets whose user_id matches their verified Supabase subject;
- admin capabilities are checked on the backend for every action;
- service-role credentials never reach the browser;
- user and admin message reads are scoped to the ticket;
- direct anon/authenticated table access remains revoked;
- rate-limit ticket creation and replies; enforce body, attachment and request-size limits;
- sanitize output and render message bodies as text, not HTML;
- avoid logging raw message bodies, credentials or private attachments;
- audit privileged reads and all privileged mutations;
- provide retention, export and deletion rules after legal review.

Atomic database functions must create a ticket and first message together, and append a message and update ticket state together. A timeout after a write must be handled safely; add idempotency keys before retryable client submission is introduced.

## 7. Feedback board and product requests

Private feedback is the default. Later, add a separate public **“Идеи и предложения”** board:

- user explicitly opts in to publish a sanitized suggestion;
- private support conversation and identity remain private;
- public cards can be tagged, searched, voted on and marked planned / in progress / shipped / declined;
- administrators can merge duplicates and publish status updates;
- users can withdraw or edit their public suggestion;
- no public vote count is treated as a promise or product commitment.

A public feedback board is not the same as a community chat and should not be launched before moderation and anti-spam controls.

## 8. Acceptance criteria

Support v1 is ready for a controlled release only when:

1. Ticket plus first message is atomic.
2. Reply plus status/timestamp update is atomic.
3. User A cannot list, read, reply to or infer User B's tickets.
4. Non-admins cannot read or mutate the owner inbox.
5. Only named admin capabilities can read, reply or change status.
6. The status lifecycle behaves as documented.
7. Message content is rendered safely as text.
8. Request limits, rate limits and clear error states are tested.
9. The support UI works on Android Chrome and desktop at narrow widths.
10. No private AI Companion conversation is exposed to support staff.
11. Live Supabase migration and deployed API/UI are verified separately from CI.
12. Email/push notifications are not advertised until they actually work.

## 9. Product references reviewed

- Intercom separates quick conversations from customer tickets, supports customer-visible status updates, internal notes and linked back-office tickets: https://www.intercom.com/help/en/articles/6436600-tickets-explained
- Intercom documents inbox assignment, views, macros and workflows: https://www.intercom.com/help/en/articles/10223008-setting-up-the-inbox
- Intercom documents SLA targets for conversations and tickets: https://www.intercom.com/help/en/articles/6546152-set-slas-for-conversations-and-tickets

PWA Studio should borrow the useful workflow patterns, not the enterprise complexity or the proprietary UI.
