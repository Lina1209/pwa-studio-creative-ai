# Financial authorization and approval model

**Status:** partially implemented in the review branch; not deployed or activated in production.  
**Scope:** delegated role assignment, credit-compensation proposals, cash-refund proposals, approval/rejection, cancellation, queue visibility, and append-only request history. This implementation does not execute either financial operation.

## 1. Current verified baseline

- Backend identity is derived from a verified Supabase Auth access token. The immutable JWT `sub` UUID is the identity key; email is display/contact data only.
- `OWNER_USER_IDS` is a server-side UUID allowlist. Empty or malformed configuration grants no owner role.
- Authentication still exposes the core product roles `admin` and `creator`; delegated finance roles are resolved separately from the private finance registry.
- The owner capability set includes the narrowly scoped `admin.finance.roles.manage` permission for role administration. Finance operator, approver, and auditor permissions are derived from active, expiring, explicitly scoped registry assignments.
- The review branch contains the request/approval/cancellation workflow and scoped queue/timeline APIs. There is no credit-ledger execution endpoint or payment-provider refund workflow.
- Supabase service-role credentials remain server-only. Browser clients and ordinary authenticated users never receive direct finance-table or service-role privileges.

The owner allowlist is not a finance permission system. Do not use `require_admin` alone as authorization for delegated financial actions. The current implementation checks the exact delegated permission and target scope on every request.

### Registry implementation checkpoint

The branch contains private role assignments, append-only grant/revocation events, server-only RPCs, owner-gated management API and UI, and integration tests for RLS, grants, revocations, self-assignment rejection, duplicate assignments, and service-role-only execution. New assignments require an explicit scope and finite expiry. These migrations have only been added to the review branch; they have not been applied to production. No real finance roles are assigned yet.


### Registry schema checkpoint (migration 0037)

The private registry foundation now defines immutable `finance_role_assignments`, append-only `finance_role_revocations`, and `finance_authorization_events`. Assignments are keyed by Supabase Auth UUID, may be limited to a `scope_key`, and support explicit validity windows. Revocation is a separate append-only fact; grant rows are never edited. RLS is enabled and direct table privileges are revoked from `public`, `anon`, `authenticated`, and `service_role`. The disposable PostgreSQL integration test checks these boundaries and rejects history updates/deletes.

Migration 0038 now adds three `SECURITY DEFINER` RPCs: `read_active_finance_role_assignments`, `grant_finance_role`, and `revoke_finance_role`. They are executable only by `service_role`; browser roles cannot invoke them. Grant and revoke each append a matching authorization event in the same database transaction, and the read RPC excludes expired or revoked assignments. The integration test verifies the full grant → read → revoke lifecycle and the RPC privilege boundary.

These RPCs are trusted backend primitives, not a complete authorization boundary by themselves. The implemented API derives the actor from the verified JWT and requires the separate owner-only `admin.finance.roles.manage` capability before calling them. Migration 0039 also rejects self-assignment inside the database RPC, even if a backend caller is misconfigured. Migration 0040 serializes grants for the same principal/role/scope and rejects duplicate active assignments. Backend permission resolution keeps scope boundaries per permission, so an operator grant for one scope cannot inherit an approver grant's separate scope. Any scoped permission check must also provide an explicit target scope; omitting it fails closed. An unscoped assignment is treated as global only for the permissions belonging to that assigned role. No real finance role has been assigned.


### Current implementation checkpoint

The backend contains `finance_authorization.py` for fail-closed permission and separation-of-duties checks, plus `finance_registry.py` for server-only role resolution and management. `POST /api/admin/finance/roles`, `GET /api/admin/finance/roles/{target_user_id}`, and `POST /api/admin/finance/roles/{assignment_id}/revoke` are protected by the explicit owner capability. The owner technical console now includes a role grant/list/revoke interface. Registry grants and revocations are append-only and audited in the database. Finance proposal and approval routes are implemented, but approved requests cannot yet execute credit or cash movements. No real finance roles have been assigned.


## 2. Proposed role separation

| Role | Intended purpose | Default access |
| --- | --- | --- |
| **Owner** | Account/platform governance and emergency oversight | Read-only finance visibility by default; may request or approve sensitive actions only through explicit permissions and dual-control rules |
| **Finance operator** | Routine finance operations | Read approved financial reports; create compensation/refund requests; cannot approve or execute their own requests |
| **Finance approver** | Independent review | Review and approve/reject requests within assigned limits; cannot approve their own request |
| **Support (read-only)** | Customer support investigation | Minimal customer/job/credit history needed for support; no financial mutation or cash/payment data beyond masked references |
| **Auditor (read-only)** | Independent control and reconciliation | Immutable event history, approval decisions, reconciliation reports; no mutation |
| **Creator** | Normal product user | Own wallet and own transaction history only |

A person may hold more than one role only where policy explicitly permits it. Conflicting role combinations must not weaken separation of duties. In particular, a request creator must never approve or execute that same request.

## 3. Permission vocabulary

Use stable, explicit permission identifiers rather than scattered role-name checks:

### Credit compensation
- `credit.compensation.read`
- `credit.compensation.request`
- `credit.compensation.approve`
- `credit.compensation.execute`
- `credit.compensation.cancel` (only before execution; audited)

### Cash refund
- `billing.refund.read`
- `billing.refund.request`
- `billing.refund.approve`
- `billing.refund.execute`
- `billing.refund.cancel` (only before provider submission; audited)

### Oversight
- `finance.audit.read`
- `finance.reconciliation.read`
- `finance.policy.manage` (high-risk; owner-controlled, separately audited)

Permissions are checked server-side on every request and again inside the transaction/RPC that performs a mutation. The static owner capability set is separate from delegated finance permissions. Active operator, approver, and auditor assignments are resolved server-side, and each action is checked against the matching permission and exact target scope. Hiding a button or trusting a frontend role is not authorization.

## 4. Suggested permission matrix (subject to explicit approval)

| Capability | Owner | Finance operator | Finance approver | Support | Auditor |
| --- | --- | --- | --- | --- | --- |
| Read aggregate provider costs | Yes | Yes | Yes | No | Yes |
| Read compensation audit | Yes | Scoped | Yes | No | Yes |
| Request credit compensation | Not by virtue of ownership; explicit grant only | Yes | No by default | No | No |
| Approve another operator's compensation | Explicit grant only | No | Yes | No | No |
| Execute approved compensation | Explicit grant only, with independent approval | No by default | Separate execute grant if policy allows | No | No |
| Request cash refund | Explicit grant only | Yes, scoped | No by default | No | No |
| Approve another operator's cash refund | Explicit grant only | No | Yes | No | No |
| Execute cash refund | Explicit grant only, dual control | No | Separate execute grant if policy allows | No | No |
| Change financial policy | Owner + explicit policy-management grant | No | No | No | No |
| Repair balances / alter historical ledger | Never through ordinary admin UI | No | No | No | No |

This matrix is a proposal, not a grant of permissions. No person receives a role merely because they are the owner, support staff, or repository collaborator.

## 5. Identity and assignment model

Implemented design: a private server-managed authorization registry keyed by immutable Supabase Auth UUID, not email.

Current records:
- `finance_role_assignments`: principal UUID, role code, explicit scope, validity window, assigning actor and reason.
- `finance_role_revocations`: append-only revocation fact; original grant rows are not edited.
- `finance_authorization_events`: append-only grant/revoke audit history.
- `finance_operation_requests` and `finance_operation_request_events`: proposal state and immutable request lifecycle events.

Permission overrides and global assignments are not exposed by the current workflow.

Requirements:
1. Assignments are created only by a separately authorized owner workflow, never by user self-service.
2. UUIDs must correspond to real Supabase Auth users. No placeholder identities or guessed IDs.
3. Email changes do not change identity or preserve access for a different UUID.
4. Every delegated grant must have a non-empty explicit scope, a future timezone-aware expiry, and a reason. Permanent or global finance assignments are rejected.
5. Revocation/suspension takes effect immediately on the next authorization check.
6. Authorization data is not writable by `anon` or `authenticated` clients. Backend/service access is narrowly controlled and audited.
7. Missing, stale, malformed, or unavailable authorization data fails closed.
8. Do not store secrets, payment credentials, or unnecessary personal information in the registry.

An alternative server-only environment allowlist may be acceptable for the first owner principal, but it does not scale safely to delegated finance roles and must not become a comma-separated all-powerful operator list.

## 6. Request → approve → execute lifecycle

Use a durable state machine, not a single privileged POST that performs everything:

`draft → submitted → approved → executing → succeeded`

Terminal/exception states: `rejected`, `cancelled`, `failed`, `requires_review`.

Each transition must:
- verify current principal, permission, active assignment, scope, and policy version;
- use a stable idempotency key and lock the target request/financial object;
- validate the original captured transaction/hold and remaining amount;
- record actor UUID, action, timestamp, reason, ticket, before/after state, policy version, and correlation IDs;
- append an immutable audit event in the same transaction as internal state changes;
- reject out-of-order transitions and replay with altered parameters.

For credit compensation, the final database mutation must also be atomic with the compensation event and credit ledger/lot changes. For cash refunds, provider submission and asynchronous provider confirmation must be separate states, with verified webhook reconciliation.

## 7. Dual control and risk thresholds

- Self-approval is prohibited for every compensation/refund request, regardless of amount.
- At least one independent approver is required for every credit compensation and cash refund.
- Execution must be a separate permission from approval. The same person must not approve and execute the same high-risk request.
- High-risk actions require two distinct human identities: requester + approver + (where policy requires) executor. No identity may fill two prohibited roles.
- Thresholds must be explicitly approved in the business currency and internal credit units; do not invent amounts or infer a credit-to-cash exchange rate.
- Bulk actions, policy changes, expired-lot exceptions, manual adjustments, and any cash refund should be treated as high risk until a documented risk policy says otherwise.
- Emergency break-glass access, if ever introduced, must be time-limited, narrowly scoped, independently reviewed after use, and never bypass immutable audit.

## 8. Audit and privacy controls

Every permission decision and workflow transition should capture:
- authenticated actor UUID and effective role/permission snapshot;
- target user UUID and object identifiers;
- action, outcome, reason code, ticket/reference, timestamp;
- request/idempotency/correlation IDs;
- policy and permission version;
- approval actor UUID and approval rationale, if applicable;
- immutable references to the resulting credit ledger/lot event or payment-provider refund record.

Do not log access tokens, service-role keys, card data, raw payment credentials, full webhook secrets, prompts, or unrelated user content. Read endpoints must use bounded queries, least-privilege fields, private/no-store caching, and audit access to sensitive records.

The detailed case-by-case automation checklist is maintained in [Financial authorization security test matrix](./FINANCIAL_AUTHORIZATION_TEST_MATRIX.md).

## 9. Required security tests

- Creator and unauthenticated requests cannot read privileged finance data or mutate finance state.
- Owner without the relevant scoped permission cannot execute compensation/refund actions.
- Finance operator cannot approve or execute their own request.
- Approver cannot approve a request they created, even if they hold multiple roles.
- Expired, revoked, suspended, malformed, or unavailable assignments fail closed.
- Email match with a different UUID grants no role.
- Request cannot be executed before approval or after cancellation/rejection.
- Changed-parameter idempotency replay is rejected.
- Concurrent approvals/executions cannot exceed the captured credit or cash amount.
- Scope mismatch (tenant/user/transaction/provider/currency) is rejected.
- An audit event is committed for both allowed and denied sensitive actions without leaking secrets.
- Direct browser/RLS access cannot read or mutate authorization tables or finance audit records.
- A service-role-only RPC cannot be invoked by `anon` or `authenticated`.
- Reconciliation catches deliberate wallet/lot/ledger/payment drift.

## 10. Decisions required before production activation

1. Confirm whether finance operators and approvers will exist at launch, or whether all finance workflows remain disabled until later.
2. Select the assignment owner(s) and a secure operator onboarding/offboarding process.
3. Approve the permission matrix and prohibited role combinations.
4. Approve dual-control rules and high-risk thresholds (without assuming amounts).
5. Decide whether credit compensation and cash refunds require separate teams/permissions.
6. Approve the audit retention period and support/auditor visibility.
7. For credit compensation, separately decide original-lot restoration vs adjustment-lot policy and expiry.
8. For cash refunds, select a payment provider and define provider-specific verification, idempotency, reconciliation, and legal disclosures.

## 11. Activation boundary

Migrations 0037–0045, the role registry, proposal/approval/cancellation APIs, scoped queue and event timeline, owner role-management UI, and delegated finance workspace exist in the review branch. They have not been applied or deployed to production. No real finance roles are assigned. Production owner UUID configuration does not automatically grant finance permissions. Before production activation, the migrations must be reviewed and applied through the approved deployment process, separate operator and approver accounts must receive scoped roles, and operational/legal policies must be approved. No credit ledger mutation, cash refund, payment-provider integration, or execution endpoint is enabled.


### Finance operation request lifecycle checkpoint

Migrations 0042 and 0043 add private request storage and server-only transactional RPCs for credit-compensation and billing-refund proposals. A request is created in `pending`, then may be approved, rejected, or cancelled by its requester while pending. Approval/rejection by the requester is rejected; decisions lock the row and allow only one transition from pending. Each transition writes an append-only event. The requester/idempotency-key pair is unique; exact retries return the original request, while changed payloads using the same key are rejected.

Important boundary: this is a request and decision ledger only. It does not grant credits, modify wallet balances, initiate refunds, or execute payment-provider operations. Backend endpoints and the delegated-role workspace now exist in the review branch, but the migrations have not been applied to production and no real finance roles have been assigned.


### Backend API checkpoint

The review branch now includes authenticated API routes:
- `POST /api/finance/requests` — creates a pending request after resolving the caller's active delegated grant and checking the exact permission/scope.
- `POST /api/finance/requests/{request_id}/decision` — reads the request from the server registry, checks the matching approver permission for its stored scope, and rejects self-approval.
- `POST /api/finance/requests/{request_id}/cancel` — only the original requester can cancel a pending request, with a matching scoped cancel permission.

The verified JWT subject supplies the actor identity; client-supplied actor IDs are not accepted. All endpoints use private no-store responses. Queue and event reads are bounded and scoped by the active role registry. The endpoints return proposal/decision state only; there is no execution endpoint, credit balance mutation, or payment-provider call.


### Scope boundary

The current finance request API derives scope on the server as `user:<target UUID>`; the client cannot choose or widen it. Each delegated finance permission must explicitly cover that exact target-user scope. Decision and cancellation routes re-check the scope stored in the request against its target user. Organization/tenant-wide finance scopes are intentionally not enabled until a trusted membership-to-scope mapping exists.


### Financial amount semantics

Credit-compensation proposals use whole credit units only (`currency_code=CRD`), matching the integer credit wallet. Cash-refund proposals use a three-letter uppercase currency code such as KZT, USD, EUR, or RUB and a positive monetary amount with at most four decimal places. The API and PostgreSQL both enforce the distinction; fractional credits, non-finite values, and cash refunds denominated in the internal CRD unit are rejected. These remain proposals only, not actual wallet or payment movements.


### Delegated request queue and workspace

The finance request queue is exposed through `GET /api/finance/requests`. It is filtered in PostgreSQL by two separate allowlists derived from the verified caller's active `credit.compensation.read` and `billing.refund.read` assignments. The browser cannot submit or broaden these scope lists. Pages are bounded to 100 visible rows and use a composite descending cursor `(requested_at, request_id)`; incomplete or timezone-free cursors are rejected. The queue RPC is executable only by `service_role`.

`GET /api/finance/me` returns only the authenticated caller's own allowlisted permissions and the number of assigned scopes; it does not expose scope identifiers. The delegated finance workspace uses this response for display only. Every create, cancel, approve, reject, and queue read is independently authorized by the backend against the current role registry.

Request scopes are bound to the target UUID as `user:<uuid>` in the service, RPC validation, and database constraint. A mismatch is rejected before storage. The queue returns request metadata and decision metadata only; it does not read credit ledger rows, payment-provider records, or execute approved operations. Approval means reviewed/approved, not paid or credited.

The current workspace can submit proposals, inspect the bounded queue, and allow the original requester to cancel a pending proposal or an independent approver to approve/reject it. The decision reason is retained. The append-only event timeline is available through `GET /api/finance/requests/{request_id}/events` and is loaded on demand in the workspace. Execution workflow, payment-provider integration, and credit ledger mutation remain separate future stages and are not enabled.


### Runtime validity verification

The backend independently validates the validity window returned by the server-only active-role RPC. An assignment is accepted only when `valid_from <= current time < valid_until`, both timestamps are timezone-aware, and the expiry is strictly later than the start. This is defense in depth against malformed or inconsistent authorization snapshots; the database RPC remains responsible for filtering active, non-revoked rows.
