-- Durable, owner-scoped idempotency for short-lived signed pricing quotes.
-- Quotes are immutable: a repeated key returns the original snapshot, never a new price.

create table if not exists public.generation_pricing_quotes (
  quote_id uuid primary key,
  user_id uuid not null references auth.users(id) on delete restrict,
  idempotency_key text not null,
  request_hash text not null,
  job_type text not null,
  provider text not null,
  model text not null,
  project_id uuid null,
  studio_scene_id uuid null,
  quote_snapshot jsonb not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  constraint generation_pricing_quotes_owner_key_unique
    unique (user_id, idempotency_key),
  constraint generation_pricing_quotes_key_length
    check (length(idempotency_key) between 8 and 200),
  constraint generation_pricing_quotes_request_hash
    check (request_hash ~ '^[0-9a-f]{64}$'),
  constraint generation_pricing_quotes_identity_bounds
    check (
      length(job_type) between 1 and 64
      and length(provider) between 1 and 100
      and length(model) between 1 and 200
    ),
  constraint generation_pricing_quotes_one_target
    check (project_id is null or studio_scene_id is null),
  constraint generation_pricing_quotes_snapshot_object
    check (
      jsonb_typeof(quote_snapshot) = 'object'
      and octet_length(quote_snapshot::text) <= 16384
    )
);

create index if not exists generation_pricing_quotes_expiry_idx
  on public.generation_pricing_quotes (expires_at);

alter table public.generation_pricing_quotes enable row level security;
revoke all on public.generation_pricing_quotes from anon, authenticated;
grant select on public.generation_pricing_quotes to authenticated;
grant all on public.generation_pricing_quotes to service_role;

drop policy if exists generation_pricing_quotes_select_own
  on public.generation_pricing_quotes;
create policy generation_pricing_quotes_select_own
  on public.generation_pricing_quotes
  for select to authenticated
  using (user_id = auth.uid());

create or replace function public.store_generation_pricing_quote(
  p_quote_id uuid,
  p_user_id uuid,
  p_idempotency_key text,
  p_request_hash text,
  p_job_type text,
  p_provider text,
  p_model text,
  p_project_id uuid,
  p_studio_scene_id uuid,
  p_quote_snapshot jsonb,
  p_expires_at timestamptz
)
returns table(quote_snapshot jsonb, created boolean, expired boolean)
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_quote public.generation_pricing_quotes%rowtype;
begin
  if p_quote_id is null or p_user_id is null
     or p_idempotency_key is null or length(p_idempotency_key) not between 8 and 200
     or p_request_hash is null or p_request_hash !~ '^[0-9a-f]{64}$'
     or p_job_type is null or length(p_job_type) not between 1 and 64
     or p_provider is null or length(p_provider) not between 1 and 100
     or p_model is null or length(p_model) not between 1 and 200
     or (p_project_id is not null and p_studio_scene_id is not null)
     or p_quote_snapshot is null or jsonb_typeof(p_quote_snapshot) <> 'object'
     or octet_length(p_quote_snapshot::text) > 16384
     or p_quote_snapshot ->> 'quote_id' <> p_quote_id::text
     or p_quote_snapshot ->> 'user_id' <> p_user_id::text
     or p_quote_snapshot ->> 'idempotency_key' <> p_idempotency_key
     or p_quote_snapshot ->> 'request_hash' <> p_request_hash
     or p_quote_snapshot ->> 'job_type' <> p_job_type
     or p_quote_snapshot ->> 'provider' <> p_provider
     or p_quote_snapshot ->> 'model' <> p_model
     or coalesce(p_quote_snapshot ->> 'quantity', '') !~ '^[1-9][0-9]{0,4}     or nullif(p_quote_snapshot ->> 'project_id', '') is distinct from p_project_id::text
     or nullif(p_quote_snapshot ->> 'studio_scene_id', '') is distinct from p_studio_scene_id::text
     or p_expires_at is null or p_expires_at <= now()
     or (p_quote_snapshot ->> 'expires_at')::timestamptz is distinct from p_expires_at then
    raise exception 'Invalid pricing quote persistence request' using errcode = '22023';
  end if;

  if p_project_id is not null and not exists (
    select 1 from public.projects p
     where p.id = p_project_id and p.owner_id = p_user_id
  ) then
    raise exception 'Pricing quote project is not owned by user' using errcode = '42501';
  end if;
  if p_studio_scene_id is not null and not exists (
    select 1 from public.studio_scenes s
     where s.id = p_studio_scene_id and s.user_id = p_user_id
  ) then
    raise exception 'Pricing quote scene is not owned by user' using errcode = '42501';
  end if;

  insert into public.generation_pricing_quotes(
    quote_id, user_id, idempotency_key, request_hash, job_type,
    provider, model, project_id, studio_scene_id, quote_snapshot, expires_at
  ) values (
    p_quote_id, p_user_id, p_idempotency_key, p_request_hash, p_job_type,
    p_provider, p_model, p_project_id, p_studio_scene_id, p_quote_snapshot, p_expires_at
  )
  on conflict (user_id, idempotency_key) do nothing;

  select * into v_quote
    from public.generation_pricing_quotes
   where user_id = p_user_id and idempotency_key = p_idempotency_key
   for update;

  if not found then
    raise exception 'Pricing quote persistence failed' using errcode = '55000';
  end if;

  if v_quote.request_hash <> p_request_hash
     or v_quote.job_type <> p_job_type
     or v_quote.provider <> p_provider
     or v_quote.model <> p_model
     or v_quote.quote_snapshot ->> 'quantity' <> p_quote_snapshot ->> 'quantity'
     or v_quote.project_id is distinct from p_project_id
     or v_quote.studio_scene_id is distinct from p_studio_scene_id then
    raise exception 'Pricing quote idempotency key was reused for a different request'
      using errcode = '22023';
  end if;

  return query select v_quote.quote_snapshot, v_quote.quote_id = p_quote_id,
    v_quote.expires_at <= now();
end;
$$;

revoke all on function public.store_generation_pricing_quote(
  uuid, uuid, text, text, text, text, text, uuid, uuid, jsonb, timestamptz
) from public, anon, authenticated;
grant execute on function public.store_generation_pricing_quote(
  uuid, uuid, text, text, text, text, text, uuid, uuid, jsonb, timestamptz
) to service_role;

comment on table public.generation_pricing_quotes is
  'Immutable owner-scoped pricing quote snapshots; unique idempotency keys return the original quote.';
comment on function public.store_generation_pricing_quote(
  uuid, uuid, text, text, text, text, text, uuid, uuid, jsonb, timestamptz
) is 'Stores one signed quote per owner/idempotency key; exact replays return the original quote and changed requests are rejected.';


create or replace function public.reject_generation_pricing_quote_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  raise exception 'Generation pricing quotes are immutable'
    using errcode = '55000';
end;
$$;

drop trigger if exists generation_pricing_quotes_immutable
  on public.generation_pricing_quotes;
create trigger generation_pricing_quotes_immutable
before update or delete on public.generation_pricing_quotes
for each row execute function public.reject_generation_pricing_quote_mutation();

revoke all on function public.reject_generation_pricing_quote_mutation() from public, anon, authenticated, service_role;

     or (p_quote_snapshot ->> 'quantity')::integer > 10000
     or nullif(p_quote_snapshot ->> 'project_id', '') is distinct from p_project_id::text
     or nullif(p_quote_snapshot ->> 'studio_scene_id', '') is distinct from p_studio_scene_id::text
     or p_expires_at is null or p_expires_at <= now()
     or (p_quote_snapshot ->> 'expires_at')::timestamptz is distinct from p_expires_at then
    raise exception 'Invalid pricing quote persistence request' using errcode = '22023';
  end if;

  if p_project_id is not null and not exists (
    select 1 from public.projects p
     where p.id = p_project_id and p.owner_id = p_user_id
  ) then
    raise exception 'Pricing quote project is not owned by user' using errcode = '42501';
  end if;
  if p_studio_scene_id is not null and not exists (
    select 1 from public.studio_scenes s
     where s.id = p_studio_scene_id and s.user_id = p_user_id
  ) then
    raise exception 'Pricing quote scene is not owned by user' using errcode = '42501';
  end if;

  insert into public.generation_pricing_quotes(
    quote_id, user_id, idempotency_key, request_hash, job_type,
    provider, model, project_id, studio_scene_id, quote_snapshot, expires_at
  ) values (
    p_quote_id, p_user_id, p_idempotency_key, p_request_hash, p_job_type,
    p_provider, p_model, p_project_id, p_studio_scene_id, p_quote_snapshot, p_expires_at
  )
  on conflict (user_id, idempotency_key) do nothing;

  select * into v_quote
    from public.generation_pricing_quotes
   where user_id = p_user_id and idempotency_key = p_idempotency_key
   for update;

  if not found then
    raise exception 'Pricing quote persistence failed' using errcode = '55000';
  end if;

  if v_quote.request_hash <> p_request_hash
     or v_quote.job_type <> p_job_type
     or v_quote.provider <> p_provider
     or v_quote.model <> p_model
     or v_quote.project_id is distinct from p_project_id
     or v_quote.studio_scene_id is distinct from p_studio_scene_id then
    raise exception 'Pricing quote idempotency key was reused for a different request'
      using errcode = '22023';
  end if;

  return query select v_quote.quote_snapshot, v_quote.quote_id = p_quote_id,
    v_quote.expires_at <= now();
end;
$$;

revoke all on function public.store_generation_pricing_quote(
  uuid, uuid, text, text, text, text, text, uuid, uuid, jsonb, timestamptz
) from public, anon, authenticated;
grant execute on function public.store_generation_pricing_quote(
  uuid, uuid, text, text, text, text, text, uuid, uuid, jsonb, timestamptz
) to service_role;

comment on table public.generation_pricing_quotes is
  'Immutable owner-scoped pricing quote snapshots; unique idempotency keys return the original quote.';
comment on function public.store_generation_pricing_quote(
  uuid, uuid, text, text, text, text, text, uuid, uuid, jsonb, timestamptz
) is 'Stores one signed quote per owner/idempotency key; exact replays return the original quote and changed requests are rejected.';


create or replace function public.reject_generation_pricing_quote_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  raise exception 'Generation pricing quotes are immutable'
    using errcode = '55000';
end;
$$;

drop trigger if exists generation_pricing_quotes_immutable
  on public.generation_pricing_quotes;
create trigger generation_pricing_quotes_immutable
before update or delete on public.generation_pricing_quotes
for each row execute function public.reject_generation_pricing_quote_mutation();

revoke all on function public.reject_generation_pricing_quote_mutation() from public, anon, authenticated, service_role;
