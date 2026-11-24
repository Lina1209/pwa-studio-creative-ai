# Direct Messaging and Notification Isolation Audit

Date: 2026-11-24  
Audited revision: `dda8028080f18cf422ff7dea92c367ae8ad78791`  
Scope: backend source and migration review only. No live Supabase access or database changes.

## Controls verified in source

- Conversation creation canonicalizes both UUIDs, rejects self-messaging, and relies on a unique ordered user pair.
- Conversation listing is filtered to threads where the authenticated user is one of the two participants.
- Message listing first verifies membership in the requested thread, then filters messages to the caller's sender/recipient side and excludes messages deleted from that side.
- Message edit operations filter by both message ID and authenticated sender ID.
- Per-user deletion performs a participant lookup and repeats the participant condition in the update itself.
- Sending checks for blocks in both directions and calls an atomic database rate-limit RPC before inserting a message.
- The direct-message migration enables RLS, revokes direct client writes, grants authenticated users read-only access, and limits thread/message reads to conversation participants.
- User block records are private to the user who created the block; writes are server-managed.
- Notification reads and read-state updates filter by the authenticated user's ID. Notification table writes are server-managed.
- The direct-message notification type emitted by the API is added by migration `0010_direct_message_notifications.sql`.

## Defense-in-depth item

### D1 — Message/thread participant consistency is enforced by application code, not by a database constraint

The `direct_messages` table has foreign keys to the thread and user accounts and checks that sender and recipient differ. The migration does not add a database constraint or trigger proving that sender and recipient are exactly the two members of the referenced conversation.

The current backend constructs these values from the verified sender identity and recipient route parameter, and obtains the canonical conversation row before inserting. This is not evidence of a current user-to-user data leak. However, service-role writes bypass RLS, so a future backend regression could create a message whose sender/recipient pair does not match the thread participants.

**Recommended correction:** make message insertion a narrowly scoped database RPC that verifies the sender is the authenticated application user supplied by the trusted server, verifies the recipient is the other thread participant, enforces block state and suspension state, and inserts the message in one transaction. Alternatively, add a database trigger enforcing the pair invariant for every insert/update. Keep service-role credentials private to the backend.

## Operational checks still required

1. Confirm live migration ledger and actual RLS/grants for `conversation_threads`, `direct_messages`, `user_blocks`, and `user_notifications`.
2. Confirm `0011_atomic_message_rate_limit.sql` is applied and the RPC is executable only by `service_role`.
3. Run two-account A/B tests: A cannot list/read B-only threads, mark B's messages read, edit B's messages, delete B's messages, or read/mark B's notifications.
4. Test block behavior in both directions and concurrent send/block requests.
5. Add PostgreSQL integration tests for the message/thread participant invariant before opening messaging to the public.

## Explicit non-actions

- No migration was run or applied.
- No production data, message, notification, block, or account was modified.
- No deployment, merge, or public messaging rollout was performed.

## Additional concurrency boundary — block versus send

The current send flow performs a block lookup, consumes the atomic per-user rate-limit counter, creates/loads the thread, and inserts the message as separate REST requests. The block lookup correctly checks both directions, but it is not transactionally coupled to the later insert.

This leaves a narrow time-of-check/time-of-use race: a block can be created after the send request's block lookup succeeds but before the message insert completes. The message may then be inserted even though the block operation has already succeeded. This is a concurrency consistency gap, not evidence of an existing cross-account read leak.

**Recommended correction before public messaging:** move the block-pair check and message insert into one narrowly scoped database RPC/transaction (or introduce an equivalent serialization/locking rule used by both block and send operations). The RPC must derive/validate the sender from trusted backend input, verify thread membership, enforce both-direction block state, and insert only if the pair remains unblocked. Keep the current atomic rate limiter as a separate abuse-control gate unless it is deliberately incorporated into the same transaction.

**Required integration tests:** race a send against a block in both orderings; if the block transaction commits first, the send must fail; if the send transaction commits first, the block may succeed afterward but must not retroactively alter the already-sent message. Also verify simultaneous duplicate sends and normal A-to-B/B-to-A traffic.

No RPC, trigger, migration, or live database change was created or applied as part of this audit.
