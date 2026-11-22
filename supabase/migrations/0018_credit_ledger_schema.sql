-- PWA Studio: append-only credit ledger schema foundation.
-- No credit mutation RPC, pricing, payments, or billing activation is introduced here.
-- All monetary/credit writes remain disabled until the atomic transaction RPCs and
-- adversarial integration tests described in docs/GENERATION_JOBS_AND_LEDGER_DESIGN.md exist.

do $$
begin
  if to_regclass('public.generation_jobs') is null then
    raise exception 'Migration 0018 requires public.generation_jobs and migrations 0009+.';
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.generation_jobs'::regclass
      and conname = 'generation_jobs_id_user_id_key'
  ) then
    alter table public.generation_jobs
      add constraint generation_jobs_id_user_id_key unique (id, user_id);
  end if;
end;
$$;

create table if not exists public.credit_wallets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  available_credits bigint not null default 0 check (available_credits >= 0),
  reserved_credits bigint not null default 0 check (reserved_credits >= 0),
  currency_unit text not null default 'credit' check (currency_unit = 'credit'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.credit_holds (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  amount bigint not null check (amount > 0),
  status text not null default 'held'
    check (status in ('held', 'captured', 'released')),
  quote_snapshot jsonb not null
    check (jsonb_typeof(quote_snapshot) = 'object'
       and octet_length(quote_snapshot::text) <= 16384),
  operation_key text not null check (length(operation_key) between 8 and 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  captured_at timestamptz,
  released_at timestamptz,
  constraint credit_holds_id_user_id_key unique (id, user_id),
  constraint credit_holds_one_per_job unique (job_id),
  constraint credit_holds_operation_unique unique (user_id, operation_key),
  constraint credit_holds_job_owner_fkey
    foreign key (job_id, user_id)
    references public.generation_jobs(id, user_id) on delete cascade,
  constraint credit_holds_terminal_timestamps check (
    (status = 'held' and captured_at is null and released_at is null)
    or (status = 'captured' and captured_at is not null and released_at is null)
    or (status = 'released' and released_at is not null and captured_at is null)
  )
);

create table if not exists public.credit_ledger (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete restrict,
  hold_id uuid,
  operation_type text not null check (operation_type in (
    'grant', 'reserve', 'capture', 'release', 'refund', 'adjustment'
  )),
  operation_key text not null check (length(operation_key) between 8 and 240),
  delta_available bigint not null default 0,
  delta_reserved bigint not null default 0,
  balance_available_after bigint not null check (balance_available_after >= 0),
  balance_reserved_after bigint not null check (balance_reserved_after >= 0),
  metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(metadata) = 'object'
       and octet_length(metadata::text) <= 16384),
  created_at timestamptz not null default now(),
  constraint credit_ledger_operation_unique unique (user_id, operation_key),
  constraint credit_ledger_hold_owner_fkey
    foreign key (hold_id, user_id)
    references public.credit_holds(id, user_id) on delete restrict,
  constraint credit_ledger_nonzero_delta check (
    delta_available <> 0 or delta_reserved <> 0
  )
);

create index if not exists credit_holds_user_status_idx
  on public.credit_holds(user_id, status, created_at desc);
create index if not exists credit_ledger_user_history_idx
  on public.credit_ledger(user_id, created_at desc, id desc);
create index if not exists credit_ledger_hold_idx
  on public.credit_ledger(hold_id, created_at)
  where hold_id is not null;

alter table public.credit_wallets enable row level security;
alter table public.credit_holds enable row level security;
alter table public.credit_ledger enable row level security;

revoke all on public.credit_wallets from anon, authenticated;
revoke all on public.credit_holds from anon, authenticated;
revoke all on public.credit_ledger from anon, authenticated;
grant select on public.credit_wallets, public.credit_holds, public.credit_ledger to authenticated;
grant all on public.credit_wallets, public.credit_holds, public.credit_ledger to service_role;

drop policy if exists "Users read own credit wallet" on public.credit_wallets;
create policy "Users read own credit wallet" on public.credit_wallets
  for select to authenticated using (auth.uid() = user_id);
drop policy if exists "Users read own credit holds" on public.credit_holds;
create policy "Users read own credit holds" on public.credit_holds
  for select to authenticated using (auth.uid() = user_id);
drop policy if exists "Users read own credit ledger" on public.credit_ledger;
create policy "Users read own credit ledger" on public.credit_ledger
  for select to authenticated using (auth.uid() = user_id);

-- Defense in depth: even privileged application code cannot rewrite ledger history.
create or replace function public.reject_credit_ledger_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  raise exception 'Credit ledger is append-only; record a compensating operation'
    using errcode = '55000';
end;
$$;

drop trigger if exists credit_ledger_no_update on public.credit_ledger;
create trigger credit_ledger_no_update
  before update or delete on public.credit_ledger
  for each row execute function public.reject_credit_ledger_mutation();

revoke all on function public.reject_credit_ledger_mutation() from public, anon, authenticated;

comment on table public.credit_wallets is
  'Credit balance projection. Mutations must be added only through audited atomic service-role RPCs.';
comment on table public.credit_holds is
  'One immutable quote-backed reservation per generation job; lifecycle RPCs are not yet enabled.';
comment on table public.credit_ledger is
  'Append-only credit accounting journal. Corrections require compensating entries.';
