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
