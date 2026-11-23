# Private Direct Messaging — Phase 1

## Scope
This feature is separate from support tickets, AI Companion history, and public community channels. Phase 1 establishes a private one-to-one conversation foundation only.

## Security model
- A conversation has exactly two participants in this initial schema.
- The canonical participant pair key prevents duplicate conversations regardless of who starts the chat.
- Authenticated clients never receive direct table grants or RPC execution rights.
- The backend verifies the signed-in user for every action and uses the service-role key only server-side.
- Message insertion is rejected unless the sender is a recorded participant.
- Every send requires a client-generated UUID idempotency key; retries return the original message rather than duplicating it.
- Message bodies are plain text, trimmed and limited to 5,000 characters. The UI must render as text, never HTML.
- No attachments, group chats, read receipts, user search, or public discovery are included in this phase.

## Required API authorization before UI
- List conversations only for the authenticated participant.
- Read messages only after verifying conversation membership.
- Start a conversation only for a valid recipient; add anti-abuse/rate limits before public availability.
- Send messages using the authenticated sender ID, never a client-supplied identity.
- Update last-read state only for the current participant.
- Do not expose email addresses or other private profile fields in conversation previews.

## Release gates
- Backend endpoints and tests for participant-scoped listing, reading, creation, and sending.
- Abuse controls: rate limits, recipient controls/blocking/reporting before general user rollout.
- In-app notification integration with recipient scoping.
- Moderation/audit policy before staff access to message contents.
- No attachments until private object storage, MIME verification, malware scanning, and short-lived signed URLs are implemented.
- No production migration or deployment until migration review and explicit operational approval.
