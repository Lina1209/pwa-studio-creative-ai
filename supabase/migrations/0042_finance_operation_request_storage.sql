-- Finance operation request lifecycle. This stores proposals and decisions only;
-- it does not mutate credit balances or call payment providers.
create table public.finance_operation_requests (
  id uuid primary key default gen_random_uuid(),
  requester_id uuid not null references auth.users(id) on delete restrict,
  request_type text not null check (request_type in ('credit_compensation', 'billing_refund')),
  target_user_id uuid not null references auth.users(id) on delete restrict,
  amount numeric(18,4) not null check (amount > 0),
  currency_code text not null check (currency_code ~ '^[A-Z]{3}$'),
  scope_key text not null check (length(scope_key) between 1 and 200 and scope_key = btrim(scope_key)),
  reason text not null check (length(reason) between 1 and 500 and reason = btrim(reason)),
  idempotency_key uuid not null,
  status text not null default 'pending'
    check (status in ('pending', 'approved', 'rejected', 'cancelled')),
  requested_at timestamptz not null default now(),
  decided_by uuid references auth.users(id) on delete restrict,
  decided_at timestamptz,
  decision_reason text check (decision_reason is null or (length(decision_reason) between 1 and 500 and decision_reason = btrim(decision_reason))),
  cancelled_at timestamptz,
  constraint finance_operation_request_amount_semantics check (
    (request_type = 'credit_compensation' and currency_code = 'CRD' and amount = trunc(amount))
    or (request_type = 'billing_refund' and currency_code <> 'CRD')
  ),
  constraint finance_operation_request_decision_shape check (
    (status = 'pending' and decided_by is null and decided_at is null and decision_reason is null and cancelled_at is null)
    or (status in ('approved', 'rejected') and decided_by is not null and decided_at is not null and decision_reason is not null and cancelled_at is null)
    or (status = 'cancelled' and decided_by is null and decided_at is null and decision_reason is null and cancelled_at is not null)
  ),
  constraint finance_operation_request_scope_matches_target
    check (scope_key = 'user:' || target_user_id::text),
  unique (requester_id, idempotency_key)
);

create index finance_operation_requests_queue_idx
  on public.finance_operation_requests(status, requested_at, id);
create index finance_operation_requests_target_idx
  on public.finance_operation_requests(target_user_id, requested_at desc, id desc);

create table public.finance_operation_request_events (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.finance_operation_requests(id) on delete restrict,
  actor_id uuid not null references auth.users(id) on delete restrict,
  event_type text not null check (event_type in (
    'request.created', 'request.approved', 'request.rejected', 'request.cancelled'
  )),
  previous_status text,
  new_status text not null check (new_status in ('pending', 'approved', 'rejected', 'cancelled')),
  reason text not null check (length(reason) between 1 and 500 and reason = btrim(reason)),
  occurred_at timestamptz not null default now(),
  constraint finance_operation_request_event_shape check (
    (event_type = 'request.created' and previous_status is null and new_status = 'pending')
    or (event_type = 'request.approved' and previous_status = 'pending' and new_status = 'approved')
    or (event_type = 'request.rejected' and previous_status = 'pending' and new_status = 'rejected')
    or (event_type = 'request.cancelled' and previous_status = 'pending' and new_status = 'cancelled')
  )
);
create index finance_operation_request_events_timeline_idx
  on public.finance_operation_request_events(request_id, occurred_at, id);

create or replace function public.prevent_finance_operation_request_event_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$ begin
  raise exception 'finance operation request history is append-only' using errcode = '55000';
end; $$;

create trigger finance_operation_request_events_no_mutation
  before update or delete on public.finance_operation_request_events
  for each row execute function public.prevent_finance_operation_request_event_mutation();

alter table public.finance_operation_requests enable row level security;
alter table public.finance_operation_request_events enable row level security;
revoke all on public.finance_operation_requests from public, anon, authenticated, service_role;
revoke all on public.finance_operation_request_events from public, anon, authenticated, service_role;
revoke all on function public.prevent_finance_operation_request_event_mutation()
  from public, anon, authenticated, service_role;
