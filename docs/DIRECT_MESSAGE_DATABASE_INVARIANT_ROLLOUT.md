# Direct Message / Thread Database Invariant — Safe Rollout Plan

Date: 2026-11-24
Scope: source-level design and rollout checklist only. This document does not apply SQL or change a database.

## Why this is needed

`conversation_threads` stores the canonical pair `user_a_id < user_b_id`. `direct_messages` stores `thread_id`, `sender_id`, and `recipient_id`, with foreign keys and a sender/recipient inequality check.

The current migration does not prove that the message sender and recipient are the two participants of the referenced thread. The API currently obtains the thread from the canonical sender/recipient pair and constructs message identity fields from the verified sender and route recipient. This is a useful application-layer control, but service-role database writes bypass RLS. A database invariant is therefore appropriate defense in depth.

## Required invariant

For every inserted message, and for every update that changes `thread_id`, `sender_id`, or `recipient_id`:

- The referenced thread exists.
- The sender and recipient are distinct.
- The unordered pair `{sender_id, recipient_id}` exactly equals `{user_a_id, user_b_id}` for that thread.
- No message may be reassigned to a different thread or participant pair unless the new values satisfy the same invariant.

The comparison must be order-independent because either participant may send the message.

## Preferred implementation

Use a narrowly scoped PostgreSQL trigger as a universal integrity guard, regardless of whether writes come from the current API, service-role scripts, or a future server RPC.

The trigger function should:
1. Be owned by a tightly controlled database owner.
2. Use a fixed, trusted `search_path` (or fully qualified object names).
3. Read the referenced `conversation_threads` row and compare both possible pair orderings.
4. Raise a generic integrity exception if the row is missing or the pair does not match.
5. Run on INSERT and on UPDATE OF `thread_id, sender_id, recipient_id`.
6. Avoid reading or logging message body, attachments, or other content.
7. Be covered by PostgreSQL integration tests for both sender directions, mismatched sender, mismatched recipient, unrelated thread, and attempted reassignment.

A transaction-scoped insert RPC can additionally centralize suspension/block checks and message insertion. It should not replace the universal trigger unless every possible write path is demonstrably restricted to that RPC.

## Preconditions before creating a migration

Do not author/apply a production migration until all of the following are confirmed from read-only live metadata:

- The actual schema, column types, constraints, indexes, and existing triggers.
- The applied migration ledger and exact migration runner convention.
- Whether the duplicate numeric `0005` migration prefix has already been resolved in the live history.
- The effective table owner, RLS flags, policies, and grants.
- Existing function owner, SECURITY DEFINER setting, ACL, and `search_path` conventions.
- Whether any existing rows violate the proposed invariant.

The repository currently contains duplicate `0005` migration prefixes, and the live migration ledger has not been inspected. A new migration must use the verified next migration identifier, not a guessed sequence number.

## Safe validation plan

1. Run read-only inventory against the intended Supabase project.
2. Run a SELECT-only query to identify invalid existing message/thread pairs; do not change or delete rows automatically.
3. Resolve any invalid historical rows through an explicitly reviewed repair plan.
4. Add the trigger migration in a new, uniquely numbered migration only after ledger reconciliation.
5. Run PostgreSQL integration tests in a disposable database.
6. Verify the trigger rejects mismatched pairs for both insert and participant-changing update.
7. Verify normal A-to-B and B-to-A messages still succeed.
8. Verify authenticated clients remain unable to write directly and only the intended backend credential can write.
9. Re-run the two-account A/B isolation suite before enabling public messaging.

## Current status

- API derives sender identity from the verified JWT; callers cannot select another sender through the route.
- The API creates/gets the canonical thread before inserting a message.
- Current source migration lacks the database pair invariant.
- The repository's existing expanded diagnostics can inventory constraints, triggers, function security attributes, grants, and RLS metadata, but have not been run against production.
- No live Supabase query, SQL migration, data repair, deployment, merge, or public rollout was performed.
