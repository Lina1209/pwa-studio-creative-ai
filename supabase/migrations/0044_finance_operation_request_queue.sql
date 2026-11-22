-- Bounded, scope-filtered finance request queue. Service-role only.
create or replace function public.list_finance_operation_requests(
  p_credit_scope_keys text[],
  p_billing_scope_keys text[],
  p_status text,
  p_before timestamptz,
  p_before_id uuid,
  p_limit integer
)
returns table (
  request_id uuid,
  requester_id uuid,
  request_type text,
  target_user_id uuid,
  amount numeric,
  currency_code text,
  scope_key text,
  reason text,
  status text,
  requested_at timestamptz,
  decided_by uuid,
  decided_at timestamptz,
  decision_reason text,
  cancelled_at timestamptz
)
language plpgsql
stable
security definer
set search_path = pg_catalog, public
as $$
begin
  if p_credit_scope_keys is null or p_billing_scope_keys is null
     or cardinality(p_credit_scope_keys) > 100
     or cardinality(p_billing_scope_keys) > 100
     or array_position(p_credit_scope_keys, null) is not null
     or array_position(p_billing_scope_keys, null) is not null
     or p_status is not null and p_status not in ('pending', 'approved', 'rejected', 'cancelled')
     or p_limit is null or p_limit < 1 or p_limit > 101
     or ((p_before is null) <> (p_before_id is null))
     or exists (
       select 1 from unnest(coalesce(p_credit_scope_keys, array[]::text[]) || coalesce(p_billing_scope_keys, array[]::text[])) s
        where s !~ '^user:[0-9a-fA-F-]{36}$'
     ) then
    raise exception 'invalid finance request queue query' using errcode = '22023';
  end if;

  return query
  select r.id, r.requester_id, r.request_type, r.target_user_id,
         r.amount, r.currency_code, r.scope_key, r.reason, r.status,
         r.requested_at, r.decided_by, r.decided_at, r.decision_reason,
         r.cancelled_at
    from public.finance_operation_requests r
   where (
      (r.request_type = 'credit_compensation' and r.scope_key = any(p_credit_scope_keys))
      or
      (r.request_type = 'billing_refund' and r.scope_key = any(p_billing_scope_keys))
   )
     and (p_status is null or r.status = p_status)
     and (
       p_before is null
       or (r.requested_at, r.id) < (p_before, p_before_id)
     )
   order by r.requested_at desc, r.id desc
   limit p_limit;
end;
$$;

revoke all on function public.list_finance_operation_requests(text[],text[],text,timestamptz,uuid,integer)
  from public, anon, authenticated;
grant execute on function public.list_finance_operation_requests(text[],text[],text,timestamptz,uuid,integer)
  to service_role;
