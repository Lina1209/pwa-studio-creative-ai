# Financial authorization and approval model

**Status:** design proposal only — no roles, permissions, operators, endpoints, RPCs, policies, or production settings are created or activated by this document.  
**Scope:** internal credit compensation and future cash-refund administration. This document does not authorize either operation.

## 1. Current verified baseline

- Backend identity is derived from a verified Supabase Auth access token. The immutable JWT `sub` UUID is the identity key; email is display/contact data only.
- `OWNER_USER_IDS` is a server-side UUID allowlist. Empty or malformed configuration grants no owner role.
- The current backend role vocabulary is only `admin` and `creator`. Narrow `require_permission(...)` dependencies now protect admin analytics and provider-cost reports; the owner capability set is read-only and rejects unknown/write permissions. `require_admin` remains for owner identity/status endpoints only.
- Existing admin endpoints are read-only operational reporting (site analytics and provider-cost reporting). There is no delegated finance role registry, approval workflow, compensation mutation endpoint, or payment-provider refund workflow. The current static owner read-capability allowlist is a transitional least-privilege boundary, not delegated role management.
- Supabase service-role credentials remain server-only. Browser clients and ordinary authenticated users must never receive finance mutation privileges.

The owner allowlist is not a finance permission system. Do not use `require_admin` alone as authorization for future credit or cash mutations.

### Registry schema checkpoint (migration 0037)\n\nThe private registry foundation now defines immutable `finance_role_assignments`, append-only `finance_role_revocations`, and `finance_authorization_events`. Assignments are keyed by Supabase Auth UUID, may be limited to a `scope_key`, and support explicit validity windows. Revocation is a separate append-only fact; grant rows are never edited. RLS is enabled and direct table privileges are revoked from `public`, `anon`, `authenticated`, and `service_role`. The disposable PostgreSQL integration test checks these boundaries and rejects history updates/deletes.\n\nMigration 0038 now adds three `SECURITY DEFINER` RPCs: `read_active_finance_role_assignments`, `grant_finance_role`, and `revoke_finance_role`. They are executable only by `service_role`; browser roles cannot invoke them. Grant and revoke each append a matching authorization event in the same database transaction, and the read RPC excludes expired or revoked assignments. The integration test verifies the full grant → read → revoke lifecycle and the RPC privilege boundary.\n\nThese RPCs are a trusted backend primitive, not a complete authorization boundary by themselves: the future API must derive the actor from the verified JWT, check the actor's explicit `finance.policy.manage` authority, enforce approval/dual-control policy, and only then call the RPC. No public endpoint currently exposes them, and no real finance role has been assigned. The next step is the server-side registry service and protected owner-controlled assignment/revocation workflow.\n\n\n### Current implementation checkpoint\n\nThe backend contains `finance_authorization.py` for fail-closed permission and separation-of-duties checks, plus `finance_registry.py` for server-only role resolution and management. `POST /api/admin/finance/roles`, `GET /api/admin/finance/roles/{target_user_id}`, and `POST /api/admin/finance/roles/{assignment_id}/revoke` are protected by the explicit owner capability. Registry grants and revocations are append-only and audited in the database. These controls do not yet authorize or implement credit compensation, cash refunds, or payment-provider execution. No real finance roles have been assigned.\n

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

Permissions are checked server-side on every request and again inside the transaction/RPC that performs a mutation. The current implementation only exposes a small static read-only owner capability set; it does not implement the proposed operator/approver assignments. Hiding a button or trusting a frontend role is not authorization.

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

Preferred future design: a private server-managed authorization registry keyed by immutable Supabase Auth UUID, not email.

Potential records (names are conceptual and not implemented):
- `finance_principals`: principal UUID, active/suspended state, created/updated timestamps, assigning actor.
- `finance_role_assignments`: principal UUID, role code, scope, valid-from/to, assigning actor, reason/ticket.
- `finance_permission_overrides`: optional narrowly scoped permission, expiry, reason, approving actor; avoid unless role grants prove insufficient.
- `finance_authorization_audit`: append-only record of grant, revoke, suspension, expiry, and policy changes.

Requirements:
1. Assignments are created only by a separately authorized owner workflow, never by user self-service.
2. UUIDs must correspond to real Supabase Auth users. No placeholder identities or guessed IDs.
3. Email changes do not change identity or preserve access for a different UUID.
4. Grants have explicit scope, expiry/review date, and reason.
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

## 10. Decisions required before implementation

1. Confirm whether finance operators and approvers will exist at launch, or whether all finance workflows remain disabled until later.
2. Select the assignment owner(s) and a secure operator onboarding/offboarding process.
3. Approve the permission matrix and prohibited role combinations.
4. Approve dual-control rules and high-risk thresholds (without assuming amounts).
5. Decide whether credit compensation and cash refunds require separate teams/permissions.
6. Approve the audit retention period and support/auditor visibility.
7. For credit compensation, separately decide original-lot restoration vs adjustment-lot policy and expiry.
8. For cash refunds, select a payment provider and define provider-specific verification, idempotency, reconciliation, and legal disclosures.

## 11. Activation boundary

This file is documentation only. It creates no database migration, table, RPC, API endpoint, role assignment, permission grant, scheduler, refund integration, or production configuration. Existing owner UUID configuration remains a prerequisite for owner access, but configuring it does not automatically grant finance permissions. Implementation must proceed in small reviewed steps after the decisions above are approved.
