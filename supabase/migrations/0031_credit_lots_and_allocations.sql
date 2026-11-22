-- PWA Studio: source-separated credit lots and hold allocations.
-- This migration backfills the current aggregate wallet without granting new credits.
-- It intentionally pauses legacy credit mutation RPCs until lot-aware lifecycle RPCs land.

do $$
declare
  v_wallet record;
  v_held bigint;
begin
  for v_wallet in
    select w.user_id, w.available_credits, w.reserved_credits
      from public.credit_wallets w
     order by w.user_id
  loop
    select coalesce(sum(h.amount), 0) into v_held
      from public.credit_holds h
     where h.user_id = v_wallet.user_id and h.status = 'held';

    if v_held <> v_wallet.reserved_credits then
      raise exception 'Cannot migrate wallet %: held credits % do not match reserved balance %',
        v_wallet.user_id, v_held, v_wallet.reserved_credits;
    end if;
  end loop;
end;
$$;

create table public.credit_lots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete restrict,
  lot_type text not null check (lot_type in (
    'free', 'subscription', 'purchased', 'bonus', 'adjustment', 'legacy'
  )),
  source_reference text not null check (length(source_reference) between 8 and 240),
  idempotency_key text not null check (length(idempotency_key) between 8 and 240),
  granted_credits bigint not null check (granted_credits > 0),
  available_credits bigint not null default 0 check (available_credits >= 0),
  reserved_credits bigint not null default 0 check (reserved_credits >= 0),
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint credit_lots_user_idempotency_unique unique(user_id, idempotency_key),
  constraint credit_lots_amounts_within_grant
    check (available_credits + reserved_credits <= granted_credits),
  constraint credit_lots_expiry_not_before_creation
    check (expires_at is null or expires_at > created_at)
);

create table public.credit_hold_allocations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete restrict,
  hold_id uuid not null,
  lot_id uuid not null,
  amount bigint not null check (amount > 0),
  status text not null default 'held'
    check (status in ('held', 'captured', 'released')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint credit_hold_allocations_hold_lot_unique unique(hold_id, lot_id),
  constraint credit_hold_allocations_hold_owner_fkey
    foreign key (hold_id, user_id)
    references public.credit_holds(id, user_id) on delete restrict,
  constraint credit_hold_allocations_lot_owner_fkey
    foreign key (lot_id, user_id)
    references public.credit_lots(id, user_id) on delete restrict
);

create index credit_lots_spend_order_idx
  on public.credit_lots(user_id, expires_at asc nulls last, created_at, id)
  where available_credits > 0;
create index credit_lots_expiry_idx
  on public.credit_lots(expires_at)
  where available_credits > 0 and expires_at is not null;
create index credit_hold_allocations_user_status_idx
  on public.credit_hold_allocations(user_id, status, created_at);

alter table public.credit_lots enable row level security;
alter table public.credit_hold_allocations enable row level security;
revoke all on public.credit_lots, public.credit_hold_allocations from anon, authenticated;
revoke all on public.credit_lots, public.credit_hold_allocations from service_role;
grant select on public.credit_lots, public.credit_hold_allocations to service_role;
drop policy if exists "Users read own credit lots" on public.credit_lots;
create policy "Users read own credit lots" on public.credit_lots
  for select to authenticated using (auth.uid() = user_id);
drop policy if exists "Users read own credit hold allocations" on public.credit_hold_allocations;
create policy "Users read own credit hold allocations" on public.credit_hold_allocations
  for select to authenticated using (auth.uid() = user_id);

-- Preserve existing balances as legacy lots; no new credit is created.
insert into public.credit_lots(
  user_id, lot_type, source_reference, idempotency_key,
  granted_credits, available_credits, reserved_credits, created_at
)
select w.user_id, 'legacy', 'legacy-wallet:' || w.user_id::text,
       'legacy-wallet:' || w.user_id::text,
       w.available_credits, w.available_credits, 0, w.created_at
  from public.credit_wallets w
 where w.available_credits > 0
on conflict (user_id, idempotency_key) do nothing;

-- Each existing held reservation becomes its own legacy lot and allocation.
insert into public.credit_lots(
  user_id, lot_type, source_reference, idempotency_key,
  granted_credits, available_credits, reserved_credits, created_at
)
select h.user_id, 'legacy', 'legacy-hold:' || h.id::text,
       'legacy-hold:' || h.id::text,
       h.amount, 0, h.amount, h.created_at
  from public.credit_holds h
 where h.status = 'held'
on conflict (user_id, idempotency_key) do nothing;

insert into public.credit_hold_allocations(user_id, hold_id, lot_id, amount)
select h.user_id, h.id, l.id, h.amount
  from public.credit_holds h
  join public.credit_lots l
    on l.user_id = h.user_id
   and l.idempotency_key = 'legacy-hold:' || h.id::text
 where h.status = 'held'
on conflict (hold_id, lot_id) do nothing;

-- Assert the lot projection exactly matches each aggregate wallet.
do $$
declare
  v_wallet record;
  v_available bigint;
  v_reserved bigint;
begin
  for v_wallet in select user_id, available_credits, reserved_credits from public.credit_wallets
  loop
    select coalesce(sum(available_credits), 0),
           coalesce(sum(reserved_credits), 0)
      into v_available, v_reserved
      from public.credit_lots where user_id = v_wallet.user_id;
    if v_available <> v_wallet.available_credits
       or v_reserved <> v_wallet.reserved_credits then
      raise exception 'Credit lot backfill mismatch for wallet %', v_wallet.user_id;
    end if;
  end loop;
end;
$$;

-- Legacy mutation functions update aggregate balances only. Disable them until
-- the replacement lifecycle allocates/resolves individual lots atomically.
revoke execute on function public.grant_user_credits(uuid,bigint,text,jsonb) from service_role;
revoke execute on function public.reserve_job_credits(uuid,uuid,bigint,text,jsonb) from service_role;
revoke execute on function public.release_job_credit_hold(uuid,uuid,text) from service_role;
revoke execute on function public.create_credited_generation_job_with_outbox(
  uuid,uuid,uuid,text,text,text,text,text,jsonb,jsonb,bigint
) from service_role;
revoke execute on function public.complete_credited_generation_job(uuid,text,text,text)
  from service_role;

comment on table public.credit_lots is
  'Source-separated credit lots. Mutation is paused until lot-aware grant/reserve/capture/release RPCs are installed.';
comment on table public.credit_hold_allocations is
  'Maps each held generation reservation to its source lots for deterministic FIFO capture/release.';
