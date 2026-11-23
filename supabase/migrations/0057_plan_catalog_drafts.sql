-- Subscription plan drafts are immutable planning records only.
-- They do not grant credits, activate entitlements, or enable checkout.
create table if not exists public.plan_catalog_drafts (
  id uuid primary key default gen_random_uuid(),
  plan_code text not null check (plan_code ~ '^[a-z][a-z0-9_]{2,40}$'),
  plan_version integer not null check (plan_version > 0),
  display_name text not null check (char_length(display_name) between 1 and 80),
  billing_period text not null check (billing_period in ('week','month')),
  period_days integer not null check (period_days in (7,30)),
  credits_per_period bigint not null check (credits_per_period > 0),
  price_minor bigint null check (price_minor is null or price_minor >= 0),
  currency char(3) null check (currency is null or currency ~ '^[A-Z]{3}$'),
  limits_json jsonb not null default '{}'::jsonb check (
    jsonb_typeof(limits_json) = 'object' and octet_length(limits_json::text) <= 8192
  ),
  features_json jsonb not null default '[]'::jsonb check (
    jsonb_typeof(features_json) = 'array' and octet_length(features_json::text) <= 8192
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique(plan_code,plan_version),
  check ((billing_period = 'week' and period_days = 7) or (billing_period = 'month' and period_days = 30)),
  check ((price_minor is null and currency is null) or (price_minor is not null and currency is not null))
);
create index if not exists plan_catalog_drafts_created_idx
  on public.plan_catalog_drafts(created_at desc,id desc);
alter table public.plan_catalog_drafts enable row level security;
revoke all on public.plan_catalog_drafts from public,anon,authenticated;
grant select,insert on public.plan_catalog_drafts to service_role;

create or replace function public.prevent_plan_catalog_draft_mutation()
returns trigger language plpgsql set search_path = pg_catalog,public
as $$
begin
  raise exception 'plan catalog drafts are immutable; create a new version' using errcode = '55000';
end;
$$;
drop trigger if exists plan_catalog_drafts_immutable on public.plan_catalog_drafts;
create trigger plan_catalog_drafts_immutable
before update or delete on public.plan_catalog_drafts
for each row execute function public.prevent_plan_catalog_draft_mutation();

comment on table public.plan_catalog_drafts is
  'Immutable draft subscription plans. No checkout, subscription activation, or credit grants are connected.';
