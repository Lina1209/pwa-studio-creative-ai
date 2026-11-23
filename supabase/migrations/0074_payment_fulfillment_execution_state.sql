-- Separate immutable payment facts from mutable fulfillment execution state.
-- No worker is enabled by this migration; it only defines safe state transitions.
alter table public.payment_fulfillment_outbox
  add column attempt_count integer not null default 0 check (attempt_count >= 0),
  add column available_at timestamptz not null default now(),
  add column locked_at timestamptz,
  add column lock_token uuid,
  add column last_error_code text,
  add column completed_at timestamptz,
  add column updated_at timestamptz not null default now();

drop trigger if exists payment_fulfillment_outbox_immutable
  on public.payment_fulfillment_outbox;

create or replace function public.guard_payment_fulfillment_outbox_update()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  if new.id is distinct from old.id
     or new.payment_order_id is distinct from old.payment_order_id
     or new.user_id is distinct from old.user_id
     or new.provider_code is distinct from old.provider_code
     or new.amount_minor is distinct from old.amount_minor
     or new.currency_code is distinct from old.currency_code
     or new.created_at is distinct from old.created_at then
    raise exception 'payment fulfillment purchase facts are immutable'
      using errcode = '55000';
  end if;

  if new.status is distinct from old.status
     and not (
       (old.status = 'queued' and new.status in ('processing','manual_review'))
       or (old.status = 'processing' and new.status in ('queued','completed','failed','manual_review'))
       or (old.status = 'failed' and new.status in ('queued','manual_review'))
     ) then
    raise exception 'invalid payment fulfillment status transition: % -> %', old.status, new.status
      using errcode = '23514';
  end if;

  if new.attempt_count < old.attempt_count
     or new.attempt_count > old.attempt_count + 1 then
    raise exception 'payment fulfillment attempt counter must stay or increase by one'
      using errcode = '23514';
  end if;

  if new.status = 'processing' then
    if new.lock_token is null or new.locked_at is null then
      raise exception 'processing fulfillment requires a lease token and timestamp'
        using errcode = '23514';
    end if;
  elsif new.lock_token is not null or new.locked_at is not null then
    raise exception 'non-processing fulfillment cannot retain a worker lease'
      using errcode = '23514';
  end if;

  if new.status = 'completed' then
    if old.status <> 'processing' or new.completed_at is null then
      raise exception 'completion requires a processing claim and completion timestamp'
        using errcode = '23514';
    end if;
  elsif new.completed_at is not null then
    raise exception 'only completed fulfillment may have completed_at'
      using errcode = '23514';
  end if;

  new.updated_at := now();
  return new;
end;
$$;

create trigger payment_fulfillment_outbox_update_guard
before update on public.payment_fulfillment_outbox
for each row execute function public.guard_payment_fulfillment_outbox_update();

create or replace function public.prevent_payment_fulfillment_outbox_delete()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  raise exception 'payment fulfillment handoff records cannot be deleted'
    using errcode = '55000';
end;
$$;

drop trigger if exists payment_fulfillment_outbox_no_delete
  on public.payment_fulfillment_outbox;
create trigger payment_fulfillment_outbox_no_delete
before delete on public.payment_fulfillment_outbox
for each row execute function public.prevent_payment_fulfillment_outbox_delete();

revoke all on public.payment_fulfillment_outbox from public, anon, authenticated, service_role;
grant select, insert on public.payment_fulfillment_outbox to service_role;
grant update (
  status, attempt_count, available_at, locked_at, lock_token,
  last_error_code, completed_at, updated_at
) on public.payment_fulfillment_outbox to service_role;

comment on table public.payment_fulfillment_outbox is
  'One immutable purchase handoff per settled order. Purchase facts cannot change; execution fields use guarded status transitions and worker leases. No fulfillment worker is enabled by this migration.';
