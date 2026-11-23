-- Read-only, keyset-paginated administrator credit ledger access.
-- This is a credit-unit journal, not a fiat-money/payment ledger.
create or replace function public.list_admin_credit_ledger(
  p_user_id uuid,
  p_before_created_at timestamptz default null,
  p_before_id bigint default null,
  p_limit integer default 50
)
returns table (
  entry_id bigint, user_id uuid, hold_id uuid, operation_type text,
  delta_available bigint, delta_reserved bigint,
  balance_available_after bigint, balance_reserved_after bigint,
  created_at timestamptz
)
language plpgsql stable security definer
set search_path = pg_catalog, public
as $$
begin
  if p_user_id is null or p_limit is null or p_limit < 1 or p_limit > 100
     or ((p_before_created_at is null) <> (p_before_id is null))
     or (p_before_id is not null and p_before_id < 1) then
    raise exception 'invalid admin credit ledger query' using errcode = '22023';
  end if;
  return query
  select l.id, l.user_id, l.hold_id, l.operation_type,
         l.delta_available, l.delta_reserved,
         l.balance_available_after, l.balance_reserved_after, l.created_at
    from public.credit_ledger l
   where l.user_id = p_user_id
     and (p_before_created_at is null
          or (l.created_at, l.id) < (p_before_created_at, p_before_id))
   order by l.created_at desc, l.id desc limit p_limit;
end;
$$;
revoke all on function public.list_admin_credit_ledger(uuid,timestamptz,bigint,integer)
  from public, anon, authenticated;
grant execute on function public.list_admin_credit_ledger(uuid,timestamptz,bigint,integer)
  to service_role;
comment on function public.list_admin_credit_ledger(uuid,timestamptz,bigint,integer) is
  'Read-only keyset-paginated credit-unit ledger. Backend must authorize and audit every administrator request.';
