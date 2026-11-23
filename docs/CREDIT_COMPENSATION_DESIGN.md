# Credit compensation and refund design

**Status:** design only — not implemented or enabled.  
**Scope:** internal credit compensation for service incidents is separate from a cash refund to the original payment method.

## 1. Vocabulary and hard boundary

- **Release** returns an unused reservation after a job is cancelled or fails. It is not a compensation and does not represent money returned.
- **Capture** consumes the reserved credits after successful generation. It is not proof that a payment provider collected money.
- **Credit compensation** is a separately approved credit adjustment after a captured operation, for example when a generation result is materially defective.
- **Cash refund** is a payment-provider operation returning money. It requires a verified payment transaction and provider-specific refund lifecycle. It must never be simulated by granting credits.

No workflow in this design authorizes a cash refund, chargeback reversal, subscription cancellation, or payment webhook processing.

## 2. Proposed eligibility and limits for credit compensation

A future database operation should require all of the following:

1. The target hold belongs to the target user and is in the terminal `captured` state.
2. Its linked generation job and capture ledger entry exist and agree on user, hold, job, and amount.
3. The captured allocation rows reconcile exactly to the original hold amount.
4. The request has a stable caller-supplied idempotency key, a controlled reason code, a non-empty support/ticket reference, and an authenticated operator identity.
5. The requested amount is a positive integer and the sum of all previously approved compensation events plus this event does not exceed the original captured amount.
6. The event and resulting ledger/lot mutation commit atomically. A failed insert must not leave a partially granted balance.
7. Replaying the same key with identical parameters returns the original result. Reusing it with changed user, hold, amount, reason, ticket, or operator must fail.
8. A different key cannot bypass the cumulative cap. Concurrent requests for the same hold must serialize by locking the hold row before calculating the remaining refundable/compensable amount.

A hold that is still held, released, missing, belongs to another user, or has inconsistent allocations must be rejected. A release must never be compensated as though it had been captured.

## 3. Audit record

Use an immutable event table for approved credit compensations. At minimum, retain:

- event UUID and creation timestamp;
- user UUID, original hold UUID, generation job UUID;
- original capture ledger entry identifier;
- amount and internal unit (`credit`);
- reason code and short operator note;
- support/ticket reference;
- authenticated operator UUID and, if a second-person approval policy is adopted, approver UUID;
- idempotency key (unique within its defined scope);
- resulting adjustment lot UUID and ledger entry identifier;
- policy/version identifier governing expiry and eligibility.

Do not store payment-card data, secrets, raw webhook payloads, or unnecessary personal information in this record. Corrections should be represented by a new audited event, never by editing or deleting a prior event.

## 4. Credit-lot treatment is a business decision, not an implementation default

Before enabling compensation, explicitly choose and publish one of these policies:

- **Restore original allocations:** credit is returned to the original source lots, preserving source type and expiry. This most faithfully reverses the consumed credit source, but an already-expired lot requires a separately approved exception rule.
- **Create an adjustment lot:** credit is granted as `adjustment` with a clearly disclosed expiry rule. This is operationally simpler, but must not silently convert an expired subscription/free lot into perpetual credits or alter the customer's purchased-credit rights.

The database function must not invent an expiry, extend an expired lot, or silently make credits non-expiring. The policy version and computed expiry must be snapshotted on each event. Partial compensation must be supported only if the selected policy defines how partial amounts map to original allocations.

## 5. Authorization boundary

The backend now assigns the owner administrator role only when the verified Supabase JWT `sub` UUID matches the server-only `OWNER_USER_IDS` allowlist. The verified email claim is display/contact data only and cannot grant admin access. A missing or malformed UUID allowlist fails closed. This is an owner allowlist, not a delegated finance-operator permission system; no scoped finance permissions or two-person approval mechanism exists yet.

Therefore, do not expose a compensation RPC to `authenticated`, `anon`, or the browser. Do not treat a caller-supplied `actor_user_id` as proof of authorization. Any future compensation endpoint must use the trusted backend identity returned by `require_admin`, persist that verified actor in an immutable audit event, and add a dedicated financial permission/approval policy before enabling execution. The broad Supabase service-role credential must remain server-side. The owner UUID must be explicitly verified in Supabase Authentication → Users and configured in the backend host; no email-based fallback is allowed.

For the broader role, permission, approval, and dual-control proposal, see [Financial authorization design](./FINANCIAL_AUTHORIZATION_DESIGN.md). That document is also design-only and grants no permissions.

## 6. Cash-refund workflow — separate future project

A cash refund requires a provider-specific payment record and a verified payment/refund lifecycle. At minimum:

- link to the original successful charge/payment intent and its provider;
- verify webhook signatures using the provider's official verification method;
- verify provider account, payment status, amount, currency, and event uniqueness;
- enforce cumulative refunds no greater than the captured cash amount, including concurrent and partial requests;
- use provider idempotency keys and persist request/response references without storing secrets;
- distinguish requested, pending, succeeded, failed, and reversed states;
- reconcile provider settlement/refund records against internal records;
- handle chargebacks and subscription state transitions independently;
- apply the legally required user disclosures, timing, evidence retention, and jurisdiction-specific consumer rules.

A credit adjustment must never be reported as a cash refund. A provider webhook must never be trusted solely because it contains a familiar event name.

## 7. Required tests before any activation

A future migration and backend implementation must prove at least:

- compensation of a captured hold succeeds and creates one immutable event, one auditable ledger change, and the policy-correct lot effect;
- held, released, missing, foreign-user, and inconsistent holds are rejected;
- amount zero/negative and amount above the remaining captured amount are rejected;
- cumulative partial compensation cannot exceed capture, including concurrent requests;
- exact replay is idempotent and altered replay is rejected;
- a second idempotency key cannot duplicate the same compensation;
- unauthorized authenticated users cannot execute or read privileged mutation paths;
- actor identity comes from trusted backend authorization, not an arbitrary request field;
- compensation does not rewrite the original capture or historical ledger entries;
- lot expiry/source rules remain correct at and after expiry;
- reconciliation reports a healthy wallet after successful compensation and detects deliberately introduced drift;
- rollback leaves no partial event, lot, or ledger mutation.

## 8. Activation gates

No compensation RPC, admin endpoint, automatic compensation policy, payment-provider refund integration, scheduler, or production migration is created by this design document. Implementation remains blocked until the authorization model, lot-restoration/expiry policy, reason-code catalog, operator approval process, and user-facing terms are explicitly reviewed and approved.


## Readback integrity checks

The server validates finance-request readback snapshots as strictly as queue rows: request UUID must match the requested record, scope must equal `user:<target UUID>`, amount must be finite and positive, currency must be a canonical three-letter uppercase ASCII code, credit compensation must use whole `CRD` units, and cash refunds must not use `CRD`. Malformed database snapshots fail closed and are not exposed as trusted finance state.
