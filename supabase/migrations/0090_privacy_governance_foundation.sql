-- Privacy governance foundation: versioned consent, privacy request intake,
-- and metadata-only AI transfer audit. This migration does not execute exports,
-- account deletion, provider deletion, or retention purges.
create table if not exists public.privacy_consent_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  consent_scope text not null check (consent_scope in ('privacy_notice', 'vision_deepseek')),
  action text not null check (action in ('accepted', 'withdrawn')),
  policy_version text not null check (length(policy_version) between 1 and 80),
  consent_version text not null check (length(consent_version) between 1 and 80),
  source text not null default 'web_app' check (source in ('web_app', 'account_settings')),
  correlation_id uuid,
  occurred_at timestamptz not null default now()
);
create index if not exists privacy_consent_events_user_scope_idx
  on public.privacy_consent_events(user_id, consent_scope, occurred_at desc, id desc);
alter table public.privacy_consent_events enable row level security;
revoke all on public.privacy_consent_events from public, anon, authenticated, service_role;

create or replace function public.prevent_privacy_event_mutation()
returns trigger language plpgsql set search_path = pg_catalog, public
as $$
begin
  raise exception 'privacy evidence events are append-only' using errcode = '55000';
end;
$$;
drop trigger if exists privacy_consent_events_no_mutation on public.privacy_consent_events;
create trigger privacy_consent_events_no_mutation
  before update or delete on public.privacy_consent_events
  for each row execute function public.prevent_privacy_event_mutation();

create table if not exists public.privacy_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  request_type text not null check (request_type in ('access', 'export', 'correction', 'deletion')),
  status text not null default 'submitted'
    check (status in ('submitted', 'in_review', 'completed', 'rejected', 'cancelled')),
  idempotency_key uuid not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  unique(user_id, idempotency_key),
  constraint privacy_request_completion_state check (
    (status = 'completed' and completed_at is not null)
    or (status <> 'completed' and completed_at is null)
  )
);
create index if not exists privacy_requests_user_created_idx
  on public.privacy_requests(user_id, created_at desc, id desc);
alter table public.privacy_requests enable row level security;
revoke all on public.privacy_requests from public, anon, authenticated, service_role;

create or replace function public.create_privacy_request(
  p_user_id uuid, p_request_type text, p_idempotency_key uuid
)
returns jsonb language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_request public.privacy_requests%rowtype;
begin
  if p_user_id is null or p_request_type is null
     or p_request_type not in ('access','export','correction','deletion')
     or p_idempotency_key is null then
    raise exception 'invalid privacy request' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 908172));
  select * into v_request from public.privacy_requests
   where user_id = p_user_id and idempotency_key = p_idempotency_key;
  if found then
    if v_request.request_type <> p_request_type then
      raise exception 'privacy request idempotency conflict' using errcode = '23505';
    end if;
    return jsonb_build_object('id',v_request.id,'request_type',v_request.request_type,
      'status',v_request.status,'created_at',v_request.created_at,'duplicate',true);
  end if;
  insert into public.privacy_requests(user_id,request_type,idempotency_key)
  values (p_user_id,p_request_type,p_idempotency_key) returning * into v_request;
  return jsonb_build_object('id',v_request.id,'request_type',v_request.request_type,
    'status',v_request.status,'created_at',v_request.created_at,'duplicate',false);
end;
$$;

create or replace function public.list_privacy_requests_for_user(p_user_id uuid, p_limit integer default 50)
returns table(id uuid, request_type text, status text, created_at timestamptz,
              updated_at timestamptz, completed_at timestamptz)
language plpgsql stable security definer
set search_path = pg_catalog, public
as $$
begin
  if p_user_id is null or p_limit is null or p_limit not between 1 and 100 then
    raise exception 'invalid privacy request query' using errcode = '22023';
  end if;
  return query
    select r.id,r.request_type,r.status,r.created_at,r.updated_at,r.completed_at
      from public.privacy_requests r
     where r.user_id = p_user_id
     order by r.created_at desc,r.id desc
     limit p_limit;
end;
$$;

create or replace function public.record_privacy_consent_event(
  p_user_id uuid, p_consent_scope text, p_action text,
  p_policy_version text, p_consent_version text,
  p_source text default 'web_app', p_correlation_id uuid default null
)
returns uuid language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare v_id uuid;
begin
  if p_user_id is null or p_consent_scope is null or p_action is null
     or p_source is null
     or p_consent_scope not in ('privacy_notice','vision_deepseek')
     or p_action not in ('accepted','withdrawn')
     or p_policy_version is null or length(p_policy_version) not between 1 and 80
     or p_consent_version is null or length(p_consent_version) not between 1 and 80
     or p_source not in ('web_app','account_settings') then
    raise exception 'invalid privacy consent event' using errcode = '22023';
  end if;
  insert into public.privacy_consent_events(
    user_id,consent_scope,action,policy_version,consent_version,source,correlation_id
  ) values (
    p_user_id,p_consent_scope,p_action,p_policy_version,p_consent_version,p_source,p_correlation_id
  ) returning id into v_id;
  return v_id;
end;
$$;

create or replace function public.get_privacy_consent_status(p_user_id uuid)
returns table(consent_scope text, action text, policy_version text,
              consent_version text, occurred_at timestamptz, event_id uuid)
language plpgsql stable security definer
set search_path = pg_catalog, public
as $$
begin
  if p_user_id is null then raise exception 'invalid privacy subject' using errcode = '22023'; end if;
  return query
    select distinct on (e.consent_scope)
      e.consent_scope,e.action,e.policy_version,e.consent_version,e.occurred_at,e.id
    from public.privacy_consent_events e
    where e.user_id = p_user_id
    order by e.consent_scope,e.occurred_at desc,e.id desc;
end;
$$;

create table if not exists public.ai_data_transfer_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  provider text not null check (provider in ('deepseek')),
  model text not null check (length(model) between 1 and 100),
  operation text not null check (operation in ('text','vision')),
  outcome text not null check (outcome in ('attempted','succeeded','failed','unknown')),
  consent_event_id uuid,
  correlation_id uuid,
  occurred_at timestamptz not null default now()
);
create index if not exists ai_data_transfer_events_user_created_idx
  on public.ai_data_transfer_events(user_id, occurred_at desc);
alter table public.ai_data_transfer_events enable row level security;
revoke all on public.ai_data_transfer_events from public, anon, authenticated, service_role;
drop trigger if exists ai_data_transfer_events_no_mutation on public.ai_data_transfer_events;
create trigger ai_data_transfer_events_no_mutation
  before update or delete on public.ai_data_transfer_events
  for each row execute function public.prevent_privacy_event_mutation();

create or replace function public.record_ai_data_transfer_event(
  p_user_id uuid, p_provider text, p_model text, p_operation text,
  p_outcome text, p_consent_event_id uuid default null,
  p_correlation_id uuid default null
)
returns uuid language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare v_id uuid;
begin
  if p_user_id is null or p_provider is null or p_operation is null or p_outcome is null
     or p_provider not in ('deepseek')
     or p_model is null or length(p_model) not between 1 and 100
     or p_operation not in ('text','vision')
     or p_outcome not in ('attempted','succeeded','failed','unknown') then
    raise exception 'invalid AI transfer audit event' using errcode = '22023';
  end if;
  if p_operation = 'vision' and p_consent_event_id is null then
    raise exception 'Vision transfer audit requires a consent event' using errcode = '22023';
  end if;
  if p_operation = 'vision' and not exists (
    select 1
      from public.privacy_consent_events e
     where e.id = p_consent_event_id
       and e.user_id = p_user_id
       and e.consent_scope = 'vision_deepseek'
       and e.action = 'accepted'
       and not exists (
         select 1 from public.privacy_consent_events later
          where later.user_id = e.user_id
            and later.consent_scope = e.consent_scope
            and (later.occurred_at, later.id) > (e.occurred_at, e.id)
       )
  ) then
    raise exception 'Current Vision consent is missing or withdrawn' using errcode = '22023';
  end if;
  if p_operation = 'text' and p_consent_event_id is not null then
    raise exception 'Text transfer must not reference Vision consent' using errcode = '22023';
  end if;
  insert into public.ai_data_transfer_events(
    user_id,provider,model,operation,outcome,consent_event_id,correlation_id
  ) values (
    p_user_id,p_provider,p_model,p_operation,p_outcome,p_consent_event_id,p_correlation_id
  ) returning id into v_id;
  return v_id;
end;
$$;

revoke all on function public.prevent_privacy_event_mutation() from public, anon, authenticated, service_role;
revoke all on function public.create_privacy_request(uuid,text,uuid) from public, anon, authenticated;
revoke all on function public.list_privacy_requests_for_user(uuid,integer) from public, anon, authenticated;
revoke all on function public.record_privacy_consent_event(uuid,text,text,text,text,text,uuid) from public, anon, authenticated;
revoke all on function public.get_privacy_consent_status(uuid) from public, anon, authenticated;
revoke all on function public.record_ai_data_transfer_event(uuid,text,text,text,text,uuid,uuid) from public, anon, authenticated;
grant execute on function public.create_privacy_request(uuid,text,uuid) to service_role;
grant execute on function public.list_privacy_requests_for_user(uuid,integer) to service_role;
grant execute on function public.record_privacy_consent_event(uuid,text,text,text,text,text,uuid) to service_role;
grant execute on function public.get_privacy_consent_status(uuid) to service_role;
grant execute on function public.record_ai_data_transfer_event(uuid,text,text,text,text,uuid,uuid) to service_role;

comment on table public.privacy_consent_events is
  'Append-only versioned consent evidence. Stores metadata only, never prompts or uploaded media.';
comment on table public.privacy_requests is
  'Authenticated user privacy request intake/status. Submission does not itself execute export or deletion.';
comment on table public.ai_data_transfer_events is
  'Append-only metadata-only external AI transfer audit; never store prompts, image bytes, URLs or provider payloads.';
