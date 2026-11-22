-- One-transaction, owner-scoped wallet snapshot for the authenticated API.
-- This function is read-only; it does not create wallets or grant credits.
create or replace function public.get_credit_wallet_snapshot(
  p_user_id uuid,
  p_history_limit integer default 50
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_holds jsonb;
  v_ledger jsonb;
begin
  if p_user_id is null or p_history_limit is null
     or p_history_limit not between 1 and 100 then
    raise exception 'Invalid credit wallet snapshot request'
      using errcode = '22023';
  end if;

  select * into v_wallet
    from public.credit_wallets
   where user_id = p_user_id;

  select coalesce(
    jsonb_agg(to_jsonb(h) order by h.created_at desc),
    '[]'::jsonb
  ) into v_holds
  from (
    select id, job_id, amount, status, created_at
      from public.credit_holds
     where user_id = p_user_id and status = 'held'
     order by created_at desc
     limit 20
  ) h;

  select coalesce(
    jsonb_agg(to_jsonb(l) order by l.created_at desc, l.id desc),
    '[]'::jsonb
  ) into v_ledger
  from (
    select id, operation_type, operation_key,
           delta_available, delta_reserved,
           balance_available_after, balance_reserved_after, created_at
      from public.credit_ledger
     where user_id = p_user_id
     order by created_at desc, id desc
     limit p_history_limit
  ) l;

  return jsonb_build_object(
    'user_id', p_user_id,
    'currency_unit', 'credit',
    'available_credits', coalesce(v_wallet.available_credits, 0),
    'reserved_credits', coalesce(v_wallet.reserved_credits, 0),
    'holds', v_holds,
    'ledger', v_ledger
  );
end;
$$;

revoke all on function public.get_credit_wallet_snapshot(uuid, integer)
  from public, anon, authenticated;
grant execute on function public.get_credit_wallet_snapshot(uuid, integer)
  to service_role;

comment on function public.get_credit_wallet_snapshot(uuid, integer) is
  'Returns one transactionally consistent read-only wallet/holds/ledger snapshot for a server-verified user UUID. Does not create a wallet or grant credits.';
