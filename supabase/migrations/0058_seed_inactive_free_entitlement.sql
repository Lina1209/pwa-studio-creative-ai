-- Seed an inert first-use free-credit policy. No credits are granted by this migration.
-- Operators must explicitly set an amount, enable the policy, and configure
-- FREE_ENTITLEMENT_POLICY_CODE=free_initial before runtime grants can occur.
insert into public.credit_entitlement_policies(
  policy_code,policy_version,lot_type,amount,expires_in_seconds,enabled
) values (
  'free_initial',1,'free',null,2592000,false
)
on conflict (policy_code,policy_version) do nothing;

comment on table public.credit_entitlement_policies is
  'Versioned server-only grant policies. Seeded free_initial policy is inert: amount NULL and enabled false.';
