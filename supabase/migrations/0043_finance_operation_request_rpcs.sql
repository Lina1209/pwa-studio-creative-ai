-- Server-only transactional request lifecycle; no credit/payment execution.
create or replace function public.create_finance_operation_request(
  p_requester_id uuid,
  p_request_type text,
  p_target_user_id uuid,
  p_amount numeric,
  p_currency_code text,
  p_scope_key text,
  p_reason text,
  p_idempotency_key uuid
)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing public.finance_operation_requests%rowtype;
  v_id uuid;
begin
  if p_requester_id is null or p_target_user_id is null
     or p_requester_id = p_target_user_id
     or p_request_type is null or p_currency_code is null
     or p_request_type not in ('credit_compensation', 'billing_refund')
     or p_amount is null or p_amount <= 0
     or p_amount::text in ('NaN', 'Infinity', '-Infinity')
     or scale(p_amount) > 4
     or p_currency_code !~ '^[A-Z]{3}$'
     or (p_request_type = 'credit_compensation'
         and (p_currency_code <> 'CRD' or p_amount <> trunc(p_amount)))
     or (p_request_type = 'billing_refund' and p_currency_code = 'CRD')
     or p_scope_key is null or length(p_scope_key) not between 1 and 200
     or p_scope_key <> btrim(p_scope_key)
     or p_reason is null or length(p_reason) not between 1 and 500
     or p_reason <> btrim(p_reason)
     or p_idempotency_key is null then
    raise exception 'invalid finance operation request' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended(p_requester_id::text || ':' || p_idempotency_key::text, 0)
  );

  select * into v_existing
    from public.finance_operation_requests
   where requester_id = p_requester_id
     and idempotency_key = p_idempotency_key;

  if found then
    if v_existing.request_type is distinct from p_request_type
       or v_existing.target_user_id is distinct from p_target_user_id
       or v_existing.amount is distinct from p_amount
       or v_existing.currency_code is distinct from p_currency_code
       or v_existing.scope_key is distinct from p_scope_key
       or v_existing.reason is distinct from p_reason then
      raise exception 'idempotency key reused with different request data'
        using errcode = '22023';
    end if;
    return v_existing.id;
  end if;

  insert into public.finance_operation_requests(
    requester_id, request_type, target_user_id, amount, currency_code,
    scope_key, reason, idempotency_key
  ) values (
    p_requester_id, p_request_type, p_target_user_id, p_amount, p_currency_code,
    p_scope_key, p_reason, p_idempotency_key
  ) returning id into v_id;

  insert into public.finance_operation_request_events(
    request_id, actor_id, event_type, previous_status, new_status, reason
  ) values (v_id, p_requester_id, 'request.created', null, 'pending', p_reason);

  return v_id;
end;
$$;


create or replace function public.decide_finance_operation_request(
  p_request_id uuid,
  p_actor_id uuid,
  p_decision text,
  p_reason text
)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_request public.finance_operation_requests%rowtype;
  v_new_status text;
begin
  if p_request_id is null or p_actor_id is null
     or p_decision is null or p_decision not in ('approve', 'reject')
     or p_reason is null or length(p_reason) not between 1 and 500
     or p_reason <> btrim(p_reason) then
    raise exception 'invalid finance request decision' using errcode = '22023';
  end if;

  select * into v_request
    from public.finance_operation_requests
   where id = p_request_id
   for update;

  if not found then
    raise exception 'finance request not found' using errcode = 'P0002';
  end if;
  if v_request.requester_id = p_actor_id then
    raise exception 'requester cannot approve or reject own request' using errcode = '22023';
  end if;
  if v_request.status <> 'pending' then
    raise exception 'finance request is no longer pending' using errcode = '55000';
  end if;

  v_new_status := case when p_decision = 'approve' then 'approved' else 'rejected' end;

  update public.finance_operation_requests
     set status = v_new_status,
         decided_by = p_actor_id,
         decided_at = now(),
         decision_reason = p_reason
   where id = p_request_id;

  insert into public.finance_operation_request_events(
    request_id, actor_id, event_type, previous_status, new_status, reason
  ) values (
    p_request_id, p_actor_id,
    case when p_decision = 'approve' then 'request.approved' else 'request.rejected' end,
    'pending', v_new_status, p_reason
  );

  return p_request_id;
end;
$$;


create or replace function public.cancel_finance_operation_request(
  p_request_id uuid,
  p_actor_id uuid,
  p_reason text
)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_request public.finance_operation_requests%rowtype;
begin
  if p_request_id is null or p_actor_id is null
     or p_reason is null or length(p_reason) not between 1 and 500
     or p_reason <> btrim(p_reason) then
    raise exception 'invalid finance request cancellation' using errcode = '22023';
  end if;

  select * into v_request
    from public.finance_operation_requests
   where id = p_request_id
   for update;

  if not found then
    raise exception 'finance request not found' using errcode = 'P0002';
  end if;
  if v_request.requester_id <> p_actor_id then
    raise exception 'only requester may cancel the request' using errcode = '22023';
  end if;
  if v_request.status <> 'pending' then
    raise exception 'only pending finance requests may be cancelled' using errcode = '55000';
  end if;

  update public.finance_operation_requests
     set status = 'cancelled', cancelled_at = now()
   where id = p_request_id;

  insert into public.finance_operation_request_events(
    request_id, actor_id, event_type, previous_status, new_status, reason
  ) values (
    p_request_id, p_actor_id, 'request.cancelled', 'pending', 'cancelled', p_reason
  );

  return p_request_id;
end;
$$;


create or replace function public.read_finance_operation_request(p_request_id uuid)
returns table (
  request_id uuid,
  requester_id uuid,
  request_type text,
  target_user_id uuid,
  amount numeric,
  currency_code text,
  scope_key text,
  status text,
  requested_at timestamptz,
  decided_by uuid,
  decided_at timestamptz
)
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
  select r.id, r.requester_id, r.request_type, r.target_user_id,
         r.amount, r.currency_code, r.scope_key, r.status,
         r.requested_at, r.decided_by, r.decided_at
    from public.finance_operation_requests r
   where r.id = p_request_id
   limit 1
$$;


revoke all on function public.create_finance_operation_request(uuid,text,uuid,numeric,text,text,text,uuid)
  from public, anon, authenticated;
revoke all on function public.decide_finance_operation_request(uuid,uuid,text,text)
  from public, anon, authenticated;
revoke all on function public.cancel_finance_operation_request(uuid,uuid,text)
  from public, anon, authenticated;
revoke all on function public.read_finance_operation_request(uuid)
  from public, anon, authenticated;

grant execute on function public.create_finance_operation_request(uuid,text,uuid,numeric,text,text,text,uuid)
  to service_role;
grant execute on function public.decide_finance_operation_request(uuid,uuid,text,text)
  to service_role;
grant execute on function public.cancel_finance_operation_request(uuid,uuid,text)
  to service_role;
grant execute on function public.read_finance_operation_request(uuid)
  to service_role;
