-- PWA Studio: atomic private-media upload reservation + verification outbox.
-- DRAFT ONLY. Requires 0005, 0012, and 0017 in a disposable Supabase project.
-- Do NOT apply to production. Reconcile the exact schema and run the SQL
-- rollback/concurrency matrix before activation.

alter table public.media_assets
  add column if not exists bucket text not null default 'studio-media',
  add column if not exists status text not null default 'ready',
  add column if not exists version bigint not null default 1,
  add column if not exists operation_id uuid,
  add column if not exists size_bytes bigint,
  add column if not exists content_sha256 text,
  add column if not exists width integer,
  add column if not exists height integer;

alter table public.media_assets
  drop constraint if exists media_assets_status_check;
alter table public.media_assets
  add constraint media_assets_status_check
  check (status in ('pending_upload','object_uploaded','ready','upload_failed','cleanup_pending','deleted'));

alter table public.media_assets
  drop constraint if exists media_assets_version_positive;
alter table public.media_assets
  add constraint media_assets_version_positive check (version > 0);

alter table public.media_assets
  drop constraint if exists media_assets_content_sha256_check;
alter table public.media_assets
  add constraint media_assets_content_sha256_check
  check (content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$');

create table if not exists public.media_asset_outbox (
  id uuid primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  asset_id uuid not null references public.media_assets(id) on delete cascade,
  operation_id uuid not null,
  event_type text not null check (event_type in ('media_cleanup_requested','media_upload_verify_requested')),
  idempotency_key text not null check (
    length(idempotency_key) between 8 and 160
    and idempotency_key ~ '^[!-~]+$'
  ),
  status text not null default 'pending'
    check (status in ('pending','claimed','delivered','dead_letter')),
  available_at timestamptz not null default now(),
  claim_token uuid,
  claim_expires_at timestamptz,
  attempts integer not null default 0 check (attempts between 0 and 20),
  max_attempts integer not null default 8 check (max_attempts between 1 and 20),
  created_at timestamptz not null default now(),
  delivered_at timestamptz,
  constraint media_asset_outbox_owner_idempotency_unique unique(owner_id,idempotency_key),
  constraint media_asset_outbox_operation_unique unique(asset_id,operation_id,event_type),
  constraint media_asset_outbox_claim_shape check (
    (status = 'claimed' and claim_token is not null and claim_expires_at is not null)
    or (status <> 'claimed' and claim_token is null and claim_expires_at is null)
  )
);

create index if not exists media_asset_outbox_pending_idx
  on public.media_asset_outbox(available_at,created_at)
  where status='pending';

alter table public.media_asset_outbox enable row level security;
revoke all on public.media_asset_outbox from public, anon, authenticated;
grant select, insert, update, delete on public.media_asset_outbox to service_role;

create or replace function public.pwa_reserve_character_reference_upload(
  p_owner_id uuid,
  p_character_id uuid,
  p_asset_id uuid,
  p_operation_id uuid,
  p_event_id uuid,
  p_idempotency_key text,
  p_file_name text,
  p_file_type text,
  p_bucket text,
  p_storage_path text,
  p_size_bytes bigint,
  p_content_sha256 text,
  p_width integer,
  p_height integer
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing public.media_assets%rowtype;
begin
  if p_owner_id is null or p_character_id is null or p_asset_id is null
     or p_operation_id is null or p_event_id is null then
    raise exception 'invalid media reservation identifiers' using errcode='22023';
  end if;

  if p_bucket is null or p_bucket <> 'studio-media'
     or p_storage_path is null
     or p_storage_path !~ ('^' || p_owner_id::text || '/characters/' || p_character_id::text || '/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpg|webp)$')
     or p_file_name is null or length(p_file_name) not between 1 and 255
     or p_file_type is null or p_file_type not in ('image/png','image/jpeg','image/webp')
     or p_size_bytes is null or p_size_bytes < 1 or p_size_bytes > 8388608
     or p_content_sha256 is null or p_content_sha256 !~ '^[0-9a-f]{64}$'
     or p_width is null or p_height is null
     or p_width < 1 or p_height < 1 or p_width > 8192 or p_height > 8192
     or p_width::bigint * p_height::bigint > 16000000
     or p_idempotency_key is null
     or length(p_idempotency_key) not between 8 and 160
     or p_idempotency_key !~ '^[!-~]+$' then
    raise exception 'invalid media reservation data' using errcode='22023';
  end if;

  if not exists (
    select 1 from public.characters c
    where c.id=p_character_id and c.owner_id=p_owner_id
  ) then
    raise exception 'character not found' using errcode='P0002';
  end if;

  insert into public.media_assets(
    id,owner_id,project_id,character_id,file_name,file_type,bucket,status,
    storage_path,metadata,version,operation_id,size_bytes,content_sha256,width,height
  ) values (
    p_asset_id,p_owner_id,null,p_character_id,p_file_name,p_file_type,p_bucket,
    'pending_upload',p_storage_path,
    jsonb_build_object('source','character-library','validation','server'),
    1,p_operation_id,p_size_bytes,p_content_sha256,p_width,p_height
  ) on conflict (id) do nothing;

  select * into v_existing from public.media_assets
  where id=p_asset_id and owner_id=p_owner_id;
  if not found or v_existing.operation_id is distinct from p_operation_id
     or v_existing.character_id is distinct from p_character_id
     or v_existing.storage_path is distinct from p_storage_path
     or v_existing.bucket is distinct from p_bucket
     or v_existing.file_name is distinct from p_file_name
     or v_existing.file_type is distinct from p_file_type
     or v_existing.size_bytes is distinct from p_size_bytes
     or v_existing.content_sha256 is distinct from p_content_sha256
     or v_existing.width is distinct from p_width
     or v_existing.height is distinct from p_height then
    raise exception 'media reservation fingerprint conflict' using errcode='23505';
  end if;

  insert into public.media_asset_outbox(
    id,owner_id,asset_id,operation_id,event_type,idempotency_key
  ) values (
    p_event_id,p_owner_id,p_asset_id,p_operation_id,
    'media_upload_verify_requested',p_idempotency_key
  ) on conflict (owner_id,idempotency_key) do nothing;

  if not exists (
    select 1 from public.media_asset_outbox e
    where e.owner_id=p_owner_id and e.idempotency_key=p_idempotency_key
      and e.asset_id=p_asset_id and e.operation_id=p_operation_id
      and e.event_type='media_upload_verify_requested'
  ) then
    raise exception 'media idempotency key conflict' using errcode='23505';
  end if;

  return jsonb_build_object(
    'id',v_existing.id,'owner_id',v_existing.owner_id,
    'character_id',v_existing.character_id,'status',v_existing.status,
    'version',v_existing.version
  );
end;
$$;

create or replace function public.pwa_mark_character_reference_object_uploaded(
  p_owner_id uuid,
  p_asset_id uuid,
  p_operation_id uuid
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_row public.media_assets%rowtype;
begin
  update public.media_assets
  set status='object_uploaded',version=version+1
  where id=p_asset_id and owner_id=p_owner_id and operation_id=p_operation_id
    and status='pending_upload'
  returning * into v_row;
  if not found then
    select * into v_row from public.media_assets
    where id=p_asset_id and owner_id=p_owner_id and operation_id=p_operation_id;
    if not found or v_row.status not in ('object_uploaded','ready') then
      raise exception 'media upload reservation not found or stale' using errcode='P0002';
    end if;
  end if;
  return jsonb_build_object('id',v_row.id,'status',v_row.status,'version',v_row.version);
end;
$$;

revoke all on function public.pwa_reserve_character_reference_upload(
  uuid,uuid,uuid,uuid,uuid,text,text,text,text,text,bigint,text,integer,integer
) from public, anon, authenticated;
revoke all on function public.pwa_mark_character_reference_object_uploaded(uuid,uuid,uuid)
  from public, anon, authenticated;
grant execute on function public.pwa_reserve_character_reference_upload(
  uuid,uuid,uuid,uuid,uuid,text,text,text,text,text,bigint,text,integer,integer
) to service_role;
grant execute on function public.pwa_mark_character_reference_object_uploaded(uuid,uuid,uuid)
  to service_role;

comment on table public.media_asset_outbox is
  'Server-only durable work queue; no browser role may access this table.';

-- Worker claim: one row at a time, transactionally fenced with a fresh token.
create or replace function public.pwa_claim_media_upload_verification(
  p_claim_token uuid,
  p_lease_seconds integer default 120
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_event public.media_asset_outbox%rowtype;
  v_asset public.media_assets%rowtype;
begin
  if p_claim_token is null or p_lease_seconds < 10 or p_lease_seconds > 900 then
    raise exception 'invalid media outbox claim' using errcode='22023';
  end if;

  -- Expired leases are recoverable; exhausted work is terminal.
  update public.media_asset_outbox
  set status='dead_letter', claim_token=null, claim_expires_at=null
  where event_type='media_upload_verify_requested'
    and status='claimed' and claim_expires_at <= clock_timestamp()
    and attempts >= max_attempts;

  update public.media_assets a
  set status='upload_failed', version=version+1
  from public.media_asset_outbox e
  where e.asset_id=a.id and e.owner_id=a.owner_id
    and e.event_type='media_upload_verify_requested'
    and e.status='dead_letter'
    and a.status in ('pending_upload','object_uploaded');

  select * into v_event
  from public.media_asset_outbox e
  where e.event_type='media_upload_verify_requested'
    and (
      (e.status='pending' and e.available_at <= clock_timestamp() and e.attempts < e.max_attempts)
      or (e.status='claimed' and e.claim_expires_at <= clock_timestamp() and e.attempts < e.max_attempts)
    )
  order by e.available_at, e.created_at
  for update skip locked
  limit 1;

  if not found then
    return null;
  end if;

  update public.media_asset_outbox
  set status='claimed', claim_token=p_claim_token,
      claim_expires_at=clock_timestamp() + make_interval(secs => p_lease_seconds),
      attempts=attempts+1
  where id=v_event.id
  returning * into v_event;

  select * into v_asset
  from public.media_assets a
  where a.id=v_event.asset_id and a.owner_id=v_event.owner_id;

  if not found or v_asset.status not in ('pending_upload','object_uploaded') then
    update public.media_asset_outbox
    set status='dead_letter', claim_token=null, claim_expires_at=null
    where id=v_event.id and claim_token=p_claim_token;
    if found and v_asset.id is not null and v_asset.status in ('pending_upload','object_uploaded') then
      update public.media_assets set status='upload_failed',version=version+1
      where id=v_asset.id and owner_id=v_event.owner_id
        and status in ('pending_upload','object_uploaded');
    end if;
    return null;
  end if;

  return jsonb_build_object(
    'event_id',v_event.id,'owner_id',v_event.owner_id,'asset_id',v_asset.id,
    'claim_token',p_claim_token,'attempts',v_event.attempts,'max_attempts',v_event.max_attempts,
    'bucket',v_asset.bucket,'storage_path',v_asset.storage_path,
    'file_name',v_asset.file_name,'file_type',v_asset.file_type,
    'size_bytes',v_asset.size_bytes,'content_sha256',v_asset.content_sha256,
    'width',v_asset.width,'height',v_asset.height
  );
end;
$$;

-- Successful byte verification and outbox acknowledgement are one transaction.
create or replace function public.pwa_complete_media_upload_verification(
  p_owner_id uuid,
  p_asset_id uuid,
  p_event_id uuid,
  p_claim_token uuid,
  p_content_sha256 text,
  p_size_bytes bigint,
  p_file_type text,
  p_width integer,
  p_height integer
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_asset public.media_assets%rowtype;
  v_event public.media_asset_outbox%rowtype;
begin
  if p_owner_id is null or p_asset_id is null or p_event_id is null
     or p_claim_token is null or p_content_sha256 is null
     or p_content_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid media verification result' using errcode='22023';
  end if;

  select * into v_event from public.media_asset_outbox
  where id=p_event_id and owner_id=p_owner_id and asset_id=p_asset_id
    and event_type='media_upload_verify_requested'
    and status='claimed' and claim_token=p_claim_token
    and claim_expires_at > clock_timestamp()
  for update;
  if not found then
    raise exception 'media verification claim is stale' using errcode='P0002';
  end if;

  update public.media_assets
  set status='ready',version=version+1
  where id=p_asset_id and owner_id=p_owner_id and status in ('pending_upload','object_uploaded')
    and content_sha256=p_content_sha256 and size_bytes=p_size_bytes
    and file_type=p_file_type and width=p_width and height=p_height
  returning * into v_asset;
  if not found then
    raise exception 'stored media does not match reserved fingerprint' using errcode='23514';
  end if;

  update public.media_asset_outbox
  set status='delivered',claim_token=null,claim_expires_at=null,delivered_at=clock_timestamp()
  where id=p_event_id and claim_token=p_claim_token and status='claimed';
  if not found then
    raise exception 'media verification claim was lost' using errcode='P0002';
  end if;

  return jsonb_build_object('id',v_asset.id,'status',v_asset.status,'version',v_asset.version);
end;
$$;

-- Retry is token-fenced; exhausted events fail closed and never become readable.
create or replace function public.pwa_retry_media_upload_verification(
  p_owner_id uuid,
  p_asset_id uuid,
  p_event_id uuid,
  p_claim_token uuid,
  p_retry_delay_seconds integer default 60
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_event public.media_asset_outbox%rowtype;
  v_asset public.media_assets%rowtype;
begin
  if p_retry_delay_seconds < 1 or p_retry_delay_seconds > 86400 then
    raise exception 'invalid media verification retry delay' using errcode='22023';
  end if;

  select * into v_event from public.media_asset_outbox
  where id=p_event_id and owner_id=p_owner_id and asset_id=p_asset_id
    and status='claimed' and claim_token=p_claim_token
    and claim_expires_at > clock_timestamp()
  for update;
  if not found then
    raise exception 'media verification claim is stale' using errcode='P0002';
  end if;

  if v_event.attempts >= v_event.max_attempts then
    update public.media_asset_outbox
    set status='dead_letter',claim_token=null,claim_expires_at=null
    where id=p_event_id and claim_token=p_claim_token;
    update public.media_assets
    set status='upload_failed',version=version+1
    where id=p_asset_id and owner_id=p_owner_id
      and status in ('pending_upload','object_uploaded')
    returning * into v_asset;
  else
    update public.media_asset_outbox
    set status='pending',available_at=clock_timestamp() + make_interval(secs => p_retry_delay_seconds),
        claim_token=null,claim_expires_at=null
    where id=p_event_id and claim_token=p_claim_token;
    select * into v_asset from public.media_assets
    where id=p_asset_id and owner_id=p_owner_id;
  end if;

  return jsonb_build_object(
    'event_status',case when v_event.attempts >= v_event.max_attempts then 'dead_letter' else 'pending' end,
    'asset_status',v_asset.status
  );
end;
$$;

revoke all on function public.pwa_claim_media_upload_verification(uuid,integer)
  from public, anon, authenticated;
revoke all on function public.pwa_complete_media_upload_verification(uuid,uuid,uuid,uuid,text,bigint,text,integer,integer)
  from public, anon, authenticated;
revoke all on function public.pwa_retry_media_upload_verification(uuid,uuid,uuid,uuid,integer)
  from public, anon, authenticated;
grant execute on function public.pwa_claim_media_upload_verification(uuid,integer) to service_role;
grant execute on function public.pwa_complete_media_upload_verification(uuid,uuid,uuid,uuid,text,bigint,text,integer,integer)
  to service_role;
grant execute on function public.pwa_retry_media_upload_verification(uuid,uuid,uuid,uuid,integer)
  to service_role;
