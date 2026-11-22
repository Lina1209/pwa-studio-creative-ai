# PWA Studio — Admin Console and Attack-Resistance Requirements

Status: implementation specification; not a claim that every control is deployed.

## Two private admin pages

1. **Platform administration** — overview, lifetime and daily visit counters, user/account lookup, support messages, feedback and reports, announcements, plan/catalog management, currency-rate source and history, feature flags, and platform settings.
2. **Technical and finance center** — payment/provider receipts, refunds (read-only until a separate approved workflow), API/model/infrastructure costs, revenue and expense reporting, credit lots/holds/ledger/reconciliation, service health, incident/error logs, backups, security events, roles, permissions, and immutable admin audit history.

The pages are navigation groupings, not trust boundaries. Every API operation and database query must enforce permissions independently. The frontend must not decide whether a user is an administrator.

## Threat model and required defenses

- **Account takeover:** Supabase JWT signature, issuer, audience, expiry, user role and UUID subject validation; MFA for the owner and privileged operators; short session lifetime for privileged actions; re-authentication for sensitive changes; session revocation and recovery process.
- **Privilege escalation:** server-derived identity only; UUID allowlist for owner bootstrap; explicit capability permissions for finance, tariffs, users, support and technical settings; deny by default; no client-supplied role/owner/price/cost/quota values; prohibit self-approval of refunds or credit compensation.
- **Broken object-level authorization (IDOR):** scope every project, conversation, message, asset, job, payment and user query by authenticated owner or explicitly granted admin capability; return non-enumerating 404 responses for inaccessible objects.
- **Credential theft/secrets exposure:** provider and Supabase service-role keys only in server secret storage; never in frontend bundles, logs, error payloads or analytics; secret scanning; rotation and incident procedure.
- **Injection and malicious input:** strict Pydantic schemas, unknown-field rejection, parameterized SQL/RPC, output escaping in the UI, safe file-name handling, MIME plus file-signature validation, upload size/count/duration limits, and no dynamic SQL built from user input.
- **Abuse, bots and denial of service:** edge/CDN WAF and shared per-IP limits; database-backed per-user limits; concurrency ceilings, queue bounds, provider timeouts, bounded retries, payload limits, upload quotas, and spending caps. In-process limits alone are insufficient across replicas.
- **CSRF/CORS abuse:** bearer-token API auth, exact origin allowlist, no credentialed wildcard CORS, origin checks for any future cookie-authenticated mutations, SameSite/HttpOnly/Secure cookies if cookies are introduced.
- **XSS/clickjacking/browser attacks:** contextual output escaping, restrictive frontend CSP, Trusted Types where feasible, frame denial, nosniff, referrer and permissions policies, dependency review. API security headers are defense-in-depth, not a substitute for frontend CSP.
- **Financial tampering:** server-side pricing catalog, signed short-lived quotes, idempotency, atomic ledger reservations, immutable audit trail, dual control for sensitive financial operations, reconciliation, and no client-side balance authority.
- **Insider misuse:** least privilege, separate read and write capabilities, time-bounded access where possible, immutable audit events, alerts for role/price/refund changes, and periodic access review.
- **Data loss/ransomware:** private storage, encrypted backups, retention policy, restore drills, restricted backup credentials and documented incident response.

## Admin security invariants

- Owner identity is the verified Supabase JWT subject UUID in server-only OWNER_USER_IDS; email is never an authorization key.
- Admin page routes are hidden from ordinary users for UX only; backend and database policies remain authoritative.
- No direct browser writes to billing, tariffs, roles, credits, provider credentials, audit logs or reconciliation records.
- Separate read permissions from change permissions. A support operator cannot change prices; a finance reader cannot issue refunds; an admin UI view does not imply an execute permission.
- Critical changes use request → independent approval → execution, with self-approval prohibited and before/after values recorded.
- Audit logs are append-only to the application role and exclude secrets and unnecessary personal data.
- All admin endpoints return Cache-Control: private, no-store and avoid exposing raw provider metadata or internal stack traces.

## Launch gates

Before enabling the admin console or public paid generation: MFA and recovery are configured; owner UUID is configured in the hosting secret store; all admin routes have capability tests; RLS and grants are reviewed; edge rate limiting/WAF is configured; CSP is deployed on the frontend; dependency and secret scans are enabled; backup restore and incident-response exercises pass; and a security review covers IDOR, XSS, CSRF, injection, brute force, privilege escalation, replay, race conditions and spending abuse.

A successful CI run is not a penetration test. No claim of being impossible to hack or fully secure is appropriate.



### Backend and technical-console integration

The backend now exposes `GET /api/admin/audit-events`, protected by
`admin.security.audit.read`, with a bounded page size of 1–200 and private,
no-store responses. The service-role key remains server-side and is used only
to call the two audit RPCs. The technical/financial console renders the returned
safe fields and does not accept direct browser writes to the journal.

Pagination uses a composite `(occurred_at, id)` keyset cursor, so multiple events written in the same database transaction timestamp are not skipped between pages. Both cursor fields are required together.

Successful journal views are recorded as `admin.access`. Failed permission
checks for a verified signed-in user are recorded as
`admin.permission.denied`; if the audit store is unavailable, the access
denial remains enforced and a generic server warning is emitted. The journal captures the administrator identity view, aggregate site analytics, provider-cost report, audit-journal views, and the read-only per-user wallet summary. The endpoint is `GET /api/admin/financial/wallets/{target_user_id}`. The wallet summary requires `admin.finance.wallets.read`, records the verified actor and target wallet UUID, and returns only balances and aggregate counts (not ledger entries or payment details). If its audit write fails, the financial data is not returned. Other administrative reads and all future state-changing operations must be wired to the audit service before they are enabled. No payment, tariff, credit, or role mutation has been enabled by this integration.

## Append-only administrative audit journal (migration 0035)

Migration `0035_admin_audit_journal.sql` adds a dedicated `admin_audit_events` table.
The table stores only a verified actor UUID, a constrained action/outcome, a constrained
resource category, optional resource/correlation UUIDs, timestamp, and a short reason.
It intentionally does not store email addresses, access tokens, API keys, payment
credentials, prompts, or arbitrary request/response bodies.

- RLS is enabled; direct table privileges are revoked from public, anon, authenticated,
  and service_role.
- Writes and bounded reads are exposed through SECURITY DEFINER RPCs granted only to
  service_role. The application must authenticate and authorize the actor before calling
  the write RPC; the actor UUID must come from the verified JWT subject, never the browser.
- A database trigger rejects UPDATE and DELETE so ordinary application roles cannot
  rewrite or erase existing events.
- Read pagination is bounded to 1–200 records and uses a timestamp cursor.
- Action, outcome, resource category, and reason length are validated in the database.

The migration and SQL integration assertions are included in the disposable PostgreSQL
quality workflow. This establishes the database storage boundary; it does not yet mean
all admin endpoints emit events or that the admin UI exposes the journal. Those
application integrations remain a separate step. A database owner/superuser can still
alter schema or disable triggers, so production-grade tamper evidence additionally
requires restricted database ownership, protected backups, and external log export.


### Delegated finance workspace

The owner technical console now includes a scoped finance-role assignment form. It calls the existing owner-only `/api/admin/finance/roles` grant, list, and revoke routes. The owner must supply the operator/approver account UUID, a target-user scope UUID, a reason, and a future expiry. Self-assignment remains prohibited. The separate finance workspace is shown only after `GET /api/finance/me` confirms active delegated permissions; it contains a bounded queue, proposal form, independent approve/reject controls, requester cancellation, and on-demand append-only event history.

The finance queue and event timeline remain read-only with respect to balances and payment providers. An approved proposal is not an executed credit compensation or cash refund. Role assignment is active only if the backend and Supabase migrations are deployed and the finance role registry is configured; this repository work alone does not apply migrations or configure production accounts.

### Read-only finance reporting panels (review branch)

The technical/finance center now includes two read-only panels:

- **Provider costs:** owner endpoint `GET /api/admin/financial/provider-costs`, date range limited to 31 days, aggregates by provider/model and day, and distinguishes reported, estimated, and unknown cost evidence. Unknown costs are not added to the known-cost total.
- **User wallet summary:** owner endpoint `GET /api/admin/financial/wallets/{target_user_id}`, returns only available/reserved/total credits and aggregate hold/lot/allocation counts. The target UUID is supplied for lookup; access requires the separate `admin.finance.wallets.read` capability and is recorded in the append-only admin audit journal. If audit storage is unavailable, the endpoint fails closed.

The UI uses text-only DOM rendering for returned values and sends no direct browser writes to financial tables. The provider-cost report is an operational expense view, not a profit-and-loss statement. Revenue, payment fees, refunds, taxes, infrastructure invoices, and net profit must not be inferred from it. The wallet summary is not a transaction ledger and does not expose individual ledger entries.

Both panels are code in the review branch only. They do not establish that the latest frontend/backend has been deployed or that the corresponding permissions and migrations are active in production. No balances, payments, refunds, tariffs, or provider budgets are changed by these panels.

### Paginated credit ledger viewer (migration 0046)

The admin finance panel now provides a separate, read-only, keyset-paginated credit ledger view for a target user. It shows operation type, available/reserved deltas, and resulting balances. The backend requires the existing `admin.finance.wallets.read` capability, bounds each page to 100 rows, validates row identity and numeric fields, and writes a mandatory access audit event before returning the page. If audit persistence fails, the endpoint returns no financial data.

Migration `0046_admin_credit_ledger_read.sql` adds a SECURITY DEFINER read RPC with service-role-only execution and a stable `(created_at, id)` cursor. The client cannot call the RPC directly or mutate ledger rows. The migration integration suite checks RPC privileges and rejects partial cursors; backend tests cover authorization, audit failure, cursor handling, malformed rows, and sanitized upstream failures.

**Accounting boundary:** this journal records internal credit units only. It is not a fiat cashbook, payment processor transaction history, revenue statement, tax report, or profit calculation. No payment/refund processor is connected and no monetary settlement is enabled.
