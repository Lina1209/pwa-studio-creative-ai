# Initial free-credit entitlement

The first authenticated wallet read can request a one-time initial free-credit grant.
This is deliberately **off by default**.

## Activation prerequisites

1. Apply the reviewed Supabase migrations, including migration 0033 and 0058, in a controlled maintenance window after backup.
2. Decide the initial credit amount only after the provider-cost and abuse limits are approved.
3. In a privileged database migration/SQL session, explicitly configure the seeded policy. Example only — do not run until the amount has been costed:
   ```sql
   update public.credit_entitlement_policies
      set amount = 100, enabled = true, updated_at = now()
    where policy_code = 'free_initial' and policy_version = 1;
   ``
4. Set the backend-only environment variable `FREE_ENTITLEMENT_POLICY_CODE=free_initial` in Render. Never expose it in frontend code.
5. Verify idempotent retry behavior and wallet reconciliation in staging before production rollout.

The runtime grant uses the existing service-role-only `grant_user_credit_entitlement` RPC with a stable user-scoped event key. Repeated wallet reads replay the same event and must not create another credit lot. If the policy is not configured in backend settings, no grant RPC is called. If a configured policy cannot be verified, the wallet endpoint fails closed with 503.

## Explicit non-goals

- This is a one-time initial grant, not a monthly recurring allowance.
- It does not enable guest sessions, paid subscriptions, checkout, payment webhooks, or automatic renewals.
- It does not change provider budgets or pricing.
- Migration files are not applied to production by CI.
- Never enable the policy or set the environment variable until credit value, expiry, user quotas, and daily provider cost ceilings have been approved.
