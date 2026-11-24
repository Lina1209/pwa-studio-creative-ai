-- Preserve wallet, reservation, and credit-ledger history when an Auth user is deleted.
-- Source-only until the live Supabase migration ledger and retention policy are reconciled.
--
-- Financial rows intentionally retain the former auth.users UUID as a pseudonymous
-- account reference. Access to these orphaned records remains server-side only.
-- This is not a substitute for an approved retention/anonymization policy.

alter table public.credit_wallets
  drop constraint if exists credit_wallets_user_id_fkey;

alter table public.credit_reservations
  drop constraint if exists credit_reservations_user_id_fkey;

alter table public.credit_ledger
  drop constraint if exists credit_ledger_user_id_fkey;

comment on column public.credit_wallets.user_id is
  'Stable account UUID reference; intentionally not FK-cascaded to auth.users so financial history survives account deletion.';

comment on column public.credit_reservations.user_id is
  'Stable account UUID reference; intentionally retained after Auth account deletion for financial audit history.';

comment on column public.credit_ledger.user_id is
  'Stable account UUID reference; intentionally retained after Auth account deletion for financial audit history.';
