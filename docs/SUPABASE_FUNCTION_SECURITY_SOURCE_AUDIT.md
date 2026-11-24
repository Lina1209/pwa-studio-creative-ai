# Supabase function security source audit

Date: 2026-11-25  
Scope: repository-only review of migrations 0011–0014. This is not a live database audit. No SQL was executed and no production object or privilege was inspected.

## Findings

### Rate-limit RPCs (migrations 0011 and 0012)
`public.consume_message_rate_limit` and `public.consume_ai_rate_limit` are SECURITY DEFINER. Source migrations revoke EXECUTE from PUBLIC, anon, and authenticated, then grant it to service_role. Their backing tables revoke direct access from anon/authenticated and grant service_role access.

Hardening item: both functions set `search_path = public, pg_temp`, rather than an empty search path. Their table references are schema-qualified, reducing ambiguity, but current Supabase guidance recommends an empty search path for SECURITY DEFINER functions and fully qualified references. This is a hardening finding, not proof of exploitability. Confirm live function owner, effective ACL, and whether untrusted roles can create objects in schemas on the path.

### Unified credit wallet RPCs (migration 0013)
`grant_user_credits`, `reserve_user_credits`, `settle_user_credit_reservation`, `release_user_credit_reservation`, and `mark_credit_reservation_reconciliation_required` are SECURITY DEFINER. Source migrations revoke EXECUTE from PUBLIC, anon, and authenticated, then grant it to service_role. Wallet tables revoke direct access from anon, authenticated, and service_role; service_role receives SELECT only, with mutations intended through RPCs.

Hardening items:
- These functions also set `search_path = public, pg_temp`; prefer `search_path = ''` and schema-qualified references after disposable-environment tests.
- Every wallet RPC accepts `p_user_id`. This is safe only behind the trusted backend: derive the UUID from the verified authenticated principal, never from a request body or query parameter. Keep RPCs unavailable to browser roles.
- `release_user_credit_reservation` permits release from both `reserved` and `reconciliation_required`. An ambiguous provider outcome must not be released merely because a client timed out. Before billing launch, require explicit reconciliation based on provider evidence; otherwise preserve the reservation.
- Migration 0013 is source-only; its presence in Git does not establish that wallet objects exist in production.

### Admin analytics RPC (migration 0014)
`public.admin_analytics_summary` uses SECURITY DEFINER with an empty search path and schema-qualified table references. EXECUTE is revoked from PUBLIC, anon, and authenticated, then granted only to service_role. Its backend route is separately guarded by `require_admin`.

The function does not independently identify an admin caller; the trust boundary is the server-side service-role credential and the backend's verified admin guard. Do not expose this RPC to browser roles.

## Required live checks
Run `supabase/diagnostics/inspect_full_security_reconciliation.sql` only after confirming the target project. Inspect actual function owners, SECURITY DEFINER flags, settings/search_path, effective EXECUTE ACLs, table grants, RLS/policies, default privileges, trigger definitions, and Storage settings. Compare live state to source; do not infer deployment from migration files.

## Safe next actions
1. Confirm target project identity using non-secret metadata.
2. Establish whether migrations were applied by Supabase CLI, SQL Editor, or both.
3. Obtain the actual migration ledger before resolving duplicate `0005` filenames.
4. Run only SELECT-only diagnostics and retain outputs privately.
5. Test function hardening and wallet lifecycle behavior in a disposable database.
6. Create future forward migrations only after reconciliation and review.

## Status
- Repository source reviewed only.
- No live Supabase connection or query.
- No SQL migration created or applied.
- No schema, grant, RLS policy, bucket, user, wallet, or project data changed.
