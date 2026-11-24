-- Forward-only defense-in-depth for wallet grant provenance.
-- This does not create an admin or payment API; callers remain service-role only.

create or replace function public.grant_user_credits(
  p_user_id uuid,
  p_amount bigint,
  p_source text,
  p_source_reference text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_wallet public.credit_wallets%rowtype;
  v_existing public.credit_ledger%rowtype;
begin
  if p_user_id is null or p_amount is null or p_amount <= 0 or p_amount > 100000000
     or p_source is null
     or p_source not in ('plan_cycle', 'purchase', 'promo', 'admin_adjustment', 'refund')
     or p_source_reference is null or length(p_source_reference) not between 1 and 160 then
    raise exception 'Invalid credit grant parameters';
  end if;

  insert into public.credit_wallets(user_id, available_credits)
  values (p_user_id, 0)
  on conflict (user_id) do nothing;
  select * into v_wallet from public.credit_wallets where user_id = p_user_id for update;

  select * into v_existing from public.credit_ledger
   where user_id = p_user_id and event_type = 'grant'
     and source = p_source and source_reference = p_source_reference;
  if found then
    if v_existing.available_delta <> p_amount then
      raise exception 'Credit grant idempotency key reused with different amount';
    end if;
    return jsonb_build_object('status', 'already_granted',
      'available_credits', v_wallet.available_credits,
      'reserved_credits', v_wallet.reserved_credits);
  end if;

  update public.credit_wallets
    set available_credits = available_credits + p_amount, updated_at = now()
    where user_id = p_user_id
    returning * into v_wallet;

  insert into public.credit_ledger(user_id, event_type, available_delta,
    source, source_reference)
  values (p_user_id, 'grant', p_amount, p_source, p_source_reference);

  return jsonb_build_object('status', 'granted',
    'available_credits', v_wallet.available_credits,
    'reserved_credits', v_wallet.reserved_credits);
end;
$$;

revoke all on function public.grant_user_credits(uuid, bigint, text, text)
  from public, anon, authenticated;
grant execute on function public.grant_user_credits(uuid, bigint, text, text)
  to service_role;
