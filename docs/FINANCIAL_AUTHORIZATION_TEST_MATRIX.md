# Financial authorization security test matrix

**Status:** test specification only. No finance roles, permissions, endpoints, RPCs, migrations, or live financial operations are implemented by this matrix.

This matrix supplements [Financial authorization design](./FINANCIAL_AUTHORIZATION_DESIGN.md). Every case must be automated before any compensation or refund workflow is enabled.

## Test fixtures and safety

Use isolated disposable PostgreSQL and mocked payment-provider adapters. Use synthetic UUIDs created inside the test fixture; never use real customer identities or production payment data. Never connect tests to production Supabase or a live payment provider. All tests must leave production configuration unchanged.

Suggested fixture principals:
- `owner_a`: configured owner UUID, with no implicit finance permission.
- `operator_a`: active finance operator, scoped to the test tenant/account.
- `approver_b`: independent finance approver.
- `executor_c`: separately authorized executor for high-risk workflows.
- `support_d`: read-only support.
- `auditor_e`: read-only auditor.
- `creator_f`: ordinary creator.
- `suspended_g`: previously authorized but suspended principal.

These are fixture labels, not real users or proposed live assignments.

## A. Identity and role resolution

| ID | Scenario | Expected result |
| --- | --- | --- |
| AUTH-01 | Valid Supabase JWT; subject UUID is configured owner | Owner identity resolved |
| AUTH-02 | Same email as owner but different subject UUID | No owner or finance privilege |
| AUTH-03 | Email changes while subject UUID remains the same | Identity remains UUID-bound |
| AUTH-04 | Missing, malformed, or empty owner allowlist | No owner identity; fail closed |
| AUTH-05 | Malformed UUID entry mixed with valid entries | Malformed entry ignored; only valid UUIDs match |
| AUTH-06 | JWT role is `anon`, `service_role`, or another non-authenticated role | Reject token |
| AUTH-07 | Expired, invalid-signature, wrong-issuer, or wrong-audience JWT | Reject token |
| AUTH-08 | Missing or invalid UUID subject | Reject token |
| AUTH-09 | Unknown or suspended finance principal | No finance permissions |
| AUTH-10 | Authorization registry unavailable or stale beyond policy | Sensitive action denied; no cached privilege escalation |

## B. Permission and scope checks

| ID | Scenario | Expected result |
| --- | --- | --- |
| PERM-01 | Creator reads another user's wallet or finance records | Denied |
| PERM-02 | Support reads only explicitly permitted, masked support fields | Allowed within scope |
| PERM-03 | Support attempts compensation/refund request or execution | Denied |
| PERM-04 | Auditor reads immutable audit/reconciliation views | Allowed, read-only |
| PERM-05 | Auditor attempts mutation | Denied |
| PERM-06 | Owner has no explicit compensation permission | Request/approve/execute denied |
| PERM-07 | Operator has request permission within assigned scope | Request allowed |
| PERM-08 | Operator requests action outside assigned scope | Denied |
| PERM-09 | Permission is revoked or assignment expires before execution | Execution denied |
| PERM-10 | Frontend claims a role or permission not present in server registry | Ignored; server decision prevails |
| PERM-11 | Direct browser call to privileged RPC/table | Denied by database grants/RLS |
| PERM-12 | `anon` or `authenticated` invokes service-role-only finance RPC | Denied |

## C. Credit compensation separation of duties

| ID | Scenario | Expected result |
| --- | --- | --- |
| COMP-01 | Operator submits valid request tied to captured generation hold | Request recorded; no credits granted yet |
| COMP-02 | Requester attempts to approve own request, including via second role | Denied |
| COMP-03 | Independent approver approves in-scope request | Approval recorded |
| COMP-04 | Approver attempts to approve a request they created | Denied |
| COMP-05 | Execution attempted before approval | Denied |
| COMP-06 | Executor lacks explicit execute permission | Denied |
| COMP-07 | High-risk request approved and executed by prohibited same identity | Denied |
| COMP-08 | Compensation exceeds original captured amount | Denied |
| COMP-09 | Cumulative partial compensations exceed original capture | Denied |
| COMP-10 | Concurrent requests race for remaining compensable amount | Serialized; total never exceeds cap |
| COMP-11 | Idempotency key replayed with identical payload | Same outcome; no duplicate credit |
| COMP-12 | Idempotency key replayed with changed payload | Rejected |
| COMP-13 | Original hold is not captured or lacks valid generation reference | Denied |
| COMP-14 | Original allocation expired or lot policy does not permit restoration | Requires explicit policy outcome; never silently extends expiry |
| COMP-15 | Compensation succeeds | Atomic compensation event, ledger mutation, and policy-defined lot effect |
| COMP-16 | Audit write fails during mutation | Entire transaction rolls back |
| COMP-17 | Compensation is attempted as a substitute for a cash refund | Rejected as wrong operation type |

## D. Cash refund controls

| ID | Scenario | Expected result |
| --- | --- | --- |
| REF-01 | Request references a verified captured provider payment | Request recorded; no provider call yet |
| REF-02 | Request references unknown, failed, or uncaptured payment | Denied |
| REF-03 | Requester attempts self-approval | Denied |
| REF-04 | Provider amount/currency differs from internal payment record | Denied; manual review |
| REF-05 | Cumulative partial refunds exceed captured cash amount | Denied |
| REF-06 | Duplicate provider idempotency key and identical payload | No duplicate provider refund |
| REF-07 | Replayed key with altered amount/currency/payment | Rejected |
| REF-08 | Invalid webhook signature or replayed event | Rejected or deduplicated |
| REF-09 | Provider accepts request but asynchronous confirmation is pending | State remains pending; do not claim refunded |
| REF-10 | Provider reports failure | Failure recorded; no false success |
| REF-11 | Provider refund and internal record diverge | Reconciliation alert; no silent balance mutation |
| REF-12 | Refund request is cancelled before provider submission | Cancelled and audited |
| REF-13 | Refund request is cancelled after provider submission | Cancellation denied; reconcile provider state |

## E. Audit, privacy, and operational resilience

| ID | Scenario | Expected result |
| --- | --- | --- |
| AUD-01 | Allowed sensitive action | Immutable event records actor UUID, permission snapshot, reason, scope, policy version, and correlation ID |
| AUD-02 | Denied sensitive action | Denial is security-audited without leaking secrets |
| AUD-03 | Audit event is updated or deleted by application role | Denied |
| AUD-04 | Logs inspected for secrets | No JWTs, service-role keys, payment credentials, webhook secrets, or card data |
| AUD-05 | Sensitive read endpoint response | Bounded fields, no-store/private caching, scoped data |
| AUD-06 | Concurrent approval/execution | Row-level serialization and atomic state transition |
| AUD-07 | Database or authorization service unavailable | Fail closed; no mutation |
| AUD-08 | Reconciliation detects wallet/lot/ledger/provider drift | Alert and review state; no automatic unapproved repair |
| AUD-09 | Emergency access is used, if such feature is approved later | Time-limited, scoped, independently reviewed, immutable audit |
| AUD-10 | Historical ledger record is edited through ordinary admin surface | Denied; correction uses separately designed append-only process |

## F. Release gate

No compensation or cash-refund implementation may be enabled until:
1. Business owners approve the role matrix, scopes, and prohibited combinations.
2. The credit-lot restoration/expiry policy is explicitly selected.
3. Payment provider, currency rules, legal disclosures, and webhook verification are defined for cash refunds.
4. All applicable tests above pass in disposable environments.
5. Database grants/RLS, backend authorization, and transaction-level checks are independently reviewed.
6. CI results are green for the exact commit proposed for merge.
7. Production rollout and rollback plans are separately approved.

A passing test suite does not itself authorize production activation.
