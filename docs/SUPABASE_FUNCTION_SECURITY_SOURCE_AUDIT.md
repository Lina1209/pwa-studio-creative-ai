# Supabase function security source audit

Date: 2026-11-25  
Scope: repository-only review of migrations 0011–0014. This is not a live database audit. No SQL was executed and no production object or privilege was inspected.

## Findings

### 1. Rate-limit RPCs (migrations 0011 and 0012)

The functions `public.consume_message_rate_limit` and `public.consume_ai_rate_limit` are declared `SECURITY DEFINER`. Their migrations revoke EXECUTE from `PUBLIC`, `anon`, and `authenticated`, then grant it to `service_role`. Their backing tables also revoke table privileges from `anon` and `authenticated` and grant service-role access.

Source-level hardening item:
- Both functions set `search_path = public, pg_temp`, rather than an empty search path.
- Their relation references are schema-qualified as `public.message_rate_limits` and `public.ai_rate_limits`, which reduces ambiguity, but Supabase's current security guidance recommends an empty search path for SECURITY DEFINER functions and fully qualified references.
- Treat this as a hardening task to validate in a disposable environment, not as proof of an exploitable vulnerability. Confirm whether any untrusted role can create objects in schemas on the path and verify actual function owner/ACL in the live project.

### 2. Unified credit wallet RPCs (migration 0013)

The functions `grant_user_credits`, `reserve_user_credits`, `settle_user_credit_reservation`, `release_user_credit_reservation`, and `mark_credit_reservation_reconciliation_required` are SECURITY DEFINER. The migration revokes EXECUTE from `PUBLIC`, `anon`, and `authenticated`, then grants it to `service_role`. The three wallet tables revoke direct access from `anon`, `authenticated`, and `service_role`; service_role receives SELECT only, while mutations are intended to occur through the RPCs.

Source-level hardening items:
- These functions also set `search_path = public, pg_temp`; prefer `search_path = ''` with schema-qualified references after disposable-environment testing.
- All wallet RPCs accept `p_user_id`. This is acceptable only behind the trusted backend boundary: every API call must derive the user UUID from the verified authenticated principal, never from a request body or query parameter. Keep these RPCs unavailable to browser roles.
- `release_user_credit_reservation` accepts both `reserved` and `reconciliation_required` states. An ambiguous provider outcome must not be released merely because the client timed out. Before any billing launch, require an explicit reconciliation decision backed by provider outcome evidence; otherwise preserve the reservation.
- The wallet migration is still source-only. Its presence in Git does not establish that any wallet objects exist in production.

### 3. Admin analytics RPC (migration 0014)

The `public.admin_analytics_summary` function uses `SECURITY DEFINER` with an empty search path and schema-qualified table references. EXECUTE is revoked from `PUBLIC`, `anon`, and `authenticated`, and granted only to `service_role`. The backend route is separately guarded by `require_admin`.

The database function itself does not independently identify an admin caller; its trust boundary is the backend service-role credential. That is acceptable only while the credential remains server-side and the route continues to enforce the verified admin identity. Do not expose this RPC to browser roles.

## Required live checks before any change

Use `supabase/diagnostics/inspect_full_security_reconciliation.sql` on the confirmed target project to inspect:
- actual function owners, SECURITY DEFINER flags, settings/search_path, and effective EXECUTE grants;
- actual table ACLs, RLS flags and policies;
- default privileges and sequence ACLs;
- trigger definitions and Storage policies;
- migration-ledger locations/columns.

Do not infer live state from migration source. Compare the live output with the source and record each object as applied, absent, partially applied, or drifted.

## Safe next actions

1. Confirm target project identity using non-secret metadata.
2. Establish whether migrations were applied by Supabase CLI, SQL Editor, or both.
3. Obtain the actual migration ledger before resolving the duplicate `0005` filenames.
4. Run only SELECT-only diagnostics and retain outputs privately.
5. Test function hardening, grants, and wallet lifecycle behavior in a disposable database.
6. Create any future forward migration only after reconciliation and review. No production SQL should be applied as part of this audit.

## Status

- Repository source reviewed only.
- No live Supabase connection or query.
- No SQL migration created or applied.
- No schema, grant, RLS policy, bucket, user, wallet, or project data changed.
