-- PWA Studio: durable, fenced cleanup of private character media.
-- DRAFT ONLY. Requires 0005, 0012, 0017, and 0018 in a DISPOSABLE database.
-- Never apply to production. Storage deletion is performed by a separate worker.
--
-- Safety model:
--   1) request RPC locks the owner-matched character and its complete asset set,
--      tombstones assets and enqueues cleanup events in one transaction.
--   2) claim RPC rechecks surviving references and leases one event.
--   3) worker deletes the exact private object using service-role Storage.
--   4) complete RPC fences the claim, detaches the tombstone from the character,
--      and acknowledges the event atomically.
--   5) finalize RPC deletes the character only after all child assets are detached.

-- Media lifecycle metadata is server-managed. Browser roles may read their
-- own rows, but may not forge ready assets, bypass cleanup, or delete metadata
-- while a private object may still exist. Cloud-sync writes go through the
-- authenticated API and service-role RPCs.
revoke insert, update, delete on public.media_assets from public, anon, authenticated;
grant select on public.media_assets to authenticated, service_role;
grant select on public.characters to service_role;

-- Keep character deletion behind the fenced cleanup/finalization RPC sequence.
revoke delete on public.characters from public, anon, authenticated;

create index if not exists media_asset_outbox_cleanup_pending_idx
  on public.media_asset_outbox(available_at, created_at)
  where status = 'pending' and event_type = 'media_cleanup_requested';

-- Trigger guard: prevent a passport edit from introducing a reference to an
-- object whose deletion has already been requested. Existing passport fields
-- on the character being deleted are intentionally not treated as surviving
-- references by the request/claim RPCs.
create or replace function public.pwa_guard_character_cleanup_reference()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_asset record;
begin
  -- Serialize passport-pointer writes with cleanup reservation by exact object.
  for v_asset in
    select a.bucket,a.storage_path
    from public.media_assets a
    where a.owner_id = new.owner_id
      and a.storage_path is not null
      and (
        position(a.storage_path in coalesce(new.reference_data::text,'')) > 0
        or position(a.storage_path in coalesce(new.avatar_url,'')) > 0
      )
  loop
    perform pg_advisory_xact_lock(hashtextextended(
      new.owner_id::text || ':' || v_asset.bucket || ':' || v_asset.storage_path, 0
    ));
    if exists (
      select 1 from public.media_assets a
      where a.owner_id=new.owner_id and a.bucket=v_asset.bucket
        and a.storage_path=v_asset.storage_path
        and a.status in ('cleanup_pending','deleted')
    ) then
      raise exception 'character passport references media that is being removed'
        using errcode='23514';
    end if;
  end loop;
  return new;
end;
$$;

drop trigger if exists characters_guard_cleanup_reference on public.characters;
create trigger characters_guard_cleanup_reference
before insert or update of reference_data, avatar_url, owner_id
on public.characters
for each row execute function public.pwa_guard_character_cleanup_reference();

-- Block new media metadata pointers to an object once cleanup has been reserved.
create or replace function public.pwa_guard_media_cleanup_reference()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_reference record;
begin
  if new.bucket is not null and new.storage_path is not null then
    perform pg_advisory_xact_lock(hashtextextended(
      new.owner_id::text || ':' || new.bucket || ':' || new.storage_path, 0
    ));
    if exists (
      select 1 from public.media_assets pending
      where pending.id <> new.id
        and pending.owner_id = new.owner_id
        and pending.bucket = new.bucket
        and pending.storage_path = new.storage_path
        and pending.status in ('cleanup_pending','deleted')
    ) then
      raise exception 'media object is already being removed'
        using errcode='23514';
    end if;
  end if;

  -- Metadata may also carry a pointer. Serialize those writes against every
  -- known object key and reject references to cleanup-pending/deleted objects.
  for v_reference in
    select a.bucket,a.storage_path
    from public.media_assets a
    where a.id <> new.id and a.owner_id=new.owner_id
      and a.storage_path is not null
      and position(a.storage_path in coalesce(new.metadata::text,'')) > 0
  loop
    perform pg_advisory_xact_lock(hashtextextended(
      new.owner_id::text || ':' || v_reference.bucket || ':' || v_reference.storage_path, 0
    ));
    if exists (
      select 1 from public.media_assets pending
      where pending.owner_id=new.owner_id
        and pending.bucket=v_reference.bucket
        and pending.storage_path=v_reference.storage_path
        and pending.status in ('cleanup_pending','deleted')
    ) then
      raise exception 'media metadata references an object that is being removed'
        using errcode='23514';
    end if;
  end loop;
  return new;
end;
$$;

drop trigger if exists media_assets_guard_cleanup_reference on public.media_assets;
create trigger media_assets_guard_cleanup_reference
before insert or update of owner_id, bucket, storage_path, status, metadata
on public.media_assets
for each row execute function public.pwa_guard_media_cleanup_reference();

alter table public.characters
  add column if not exists cleanup_operation_id uuid,
  add column if not exists cleanup_requested_at timestamptz;


-- The deletion-intent fence itself is server-managed; a browser must not
-- set or clear it to deny service or bypass an in-progress cleanup.
create or replace function public.pwa_guard_character_cleanup_intent()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  if auth.role() = 'authenticated' then
    if tg_op = 'INSERT' then
      if new.cleanup_operation_id is not null or new.cleanup_requested_at is not null then
        raise exception 'character cleanup intent is server-managed' using errcode='42501';
      end if;
    elsif new.cleanup_operation_id is distinct from old.cleanup_operation_id
       or new.cleanup_requested_at is distinct from old.cleanup_requested_at then
      raise exception 'character cleanup intent is server-managed' using errcode='42501';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists characters_guard_cleanup_intent on public.characters;
create trigger characters_guard_cleanup_intent
before insert or update of cleanup_operation_id, cleanup_requested_at
on public.characters
for each row execute function public.pwa_guard_character_cleanup_intent();

-- Serialize media-row creation/association with character deletion intent.
-- Upload reservation RPCs insert through this trigger, so a reservation that
-- wins the character row lock is visible to cleanup; cleanup that wins first
-- marks the character and blocks later media associations.
create or replace function public.pwa_guard_character_cleanup_asset_write()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_cleanup_operation_id uuid;
begin
  if new.character_id is not null then
    select c.cleanup_operation_id into v_cleanup_operation_id
    from public.characters c
    where c.id=new.character_id and c.owner_id=new.owner_id
    for update;
    if not found then
      raise exception 'character not found' using errcode='P0002';
    end if;
    if v_cleanup_operation_id is not null then
      raise exception 'character deletion is already in progress' using errcode='23514';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists media_assets_guard_character_cleanup on public.media_assets;
create trigger media_assets_guard_character_cleanup
before insert or update of owner_id, character_id
on public.media_assets
for each row execute function public.pwa_guard_character_cleanup_asset_write();

create or replace function public.pwa_request_character_media_cleanup(
  p_owner_id uuid,
  p_character_id uuid,
  p_operation_id uuid
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_character public.characters%rowtype;
  v_asset public.media_assets%rowtype;
  v_count integer := 0;
  v_existing integer;
  v_key text;
begin
  if p_owner_id is null or p_character_id is null or p_operation_id is null then
    raise exception 'invalid character cleanup request' using errcode='22023';
  end if;

  select * into v_character
  from public.characters
  where id=p_character_id and owner_id=p_owner_id
  for update;
  if not found then
    raise exception 'character not found' using errcode='P0002';
  end if;
  if v_character.cleanup_operation_id is not null
     and v_character.cleanup_operation_id <> p_operation_id then
    raise exception 'another character cleanup operation is already in progress'
      using errcode='23514';
  end if;
  -- Refuse to discard a private object key hidden in the passport unless
  -- it has a corresponding owner-scoped media row in the complete child set.
  if exists (
    select 1
    from regexp_matches(
      coalesce(v_character.reference_data::text,'') || ' ' || coalesce(v_character.avatar_url,''),
      '(' || p_owner_id::text || '/characters/' || p_character_id::text ||
      '/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(?:png|jpg|webp))',
      'g'
    ) as passport_paths(path_parts)
    where not exists (
      select 1 from public.media_assets a
      where a.owner_id=p_owner_id and a.character_id=p_character_id
        and a.storage_path=passport_paths.path_parts[1]
    )
  ) then
    raise exception 'character passport contains an unindexed private media reference'
      using errcode='23514';
  end if;

  update public.characters
  set cleanup_operation_id=coalesce(cleanup_operation_id,p_operation_id),
      cleanup_requested_at=coalesce(cleanup_requested_at,clock_timestamp())
  where id=p_character_id and owner_id=p_owner_id;

  -- Lock the complete child set in deterministic order. Do not accept a client
  -- supplied asset list or storage path.
  for v_asset in
    select * from public.media_assets
    where owner_id=p_owner_id and character_id=p_character_id
    order by id
    for update
  loop
    if v_asset.status = 'deleted' then
      -- A legacy deleted row may still carry the restrictive character FK.
      update public.media_assets
      set character_id=null,version=version+1
      where id=v_asset.id and owner_id=p_owner_id and character_id=p_character_id;
      continue;
    end if;
    if v_asset.status in ('pending_upload','object_uploaded') then
      -- The upload request or verification worker may still be producing the
      -- object. Do not race a Storage DELETE against an in-flight upload.
      raise exception 'character has an upload in progress; retry deletion after it finishes'
        using errcode='23514';
    end if;
    if v_asset.status not in ('ready','upload_failed','cleanup_pending') then
      raise exception 'character media has an unsupported lifecycle state' using errcode='23514';
    end if;
    if v_asset.bucket <> 'studio-media'
       or v_asset.storage_path is null
       or v_asset.storage_path !~ ('^' || p_owner_id::text || '/characters/' || p_character_id::text || '/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpg|webp)$') then
      raise exception 'character media object key is invalid' using errcode='23514';
    end if;

    -- Serialize reference creation against this cleanup reservation. Both
    -- metadata triggers acquire the same transaction-scoped advisory lock.
    perform pg_advisory_xact_lock(hashtextextended(
      p_owner_id::text || ':' || v_asset.bucket || ':' || v_asset.storage_path, 0
    ));

    -- Fail closed if another row or another character passport points to this
    -- exact object. The target character's own passport is being removed.
    if exists (
      select 1 from public.media_assets other
      where other.id <> v_asset.id
        and other.bucket=v_asset.bucket
        and other.storage_path=v_asset.storage_path
        and other.status <> 'deleted'
    ) or exists (
      select 1 from public.media_assets other
      where other.id <> v_asset.id
        and position(v_asset.storage_path in coalesce(other.metadata::text,'')) > 0
        and other.status <> 'deleted'
    ) or exists (
      select 1 from public.characters other_character
      where other_character.id <> p_character_id
        and other_character.owner_id=p_owner_id
        and (
          position(v_asset.storage_path in coalesce(other_character.reference_data::text,'')) > 0
          or position(v_asset.storage_path in coalesce(other_character.avatar_url,'')) > 0
        )
    ) then
      raise exception 'character media object is still referenced' using errcode='23514';
    end if;

    v_key := 'character-cleanup:' || p_character_id::text || ':' ||
             p_operation_id::text || ':' || v_asset.id::text;

    update public.media_assets
    set status='cleanup_pending', version=version+1
    where id=v_asset.id and owner_id=p_owner_id
      and status <> 'cleanup_pending';

    insert into public.media_asset_outbox(
      id,owner_id,asset_id,operation_id,event_type,idempotency_key,
      status,available_at,max_attempts
    ) values (
      gen_random_uuid(),p_owner_id,v_asset.id,p_operation_id,
      'media_cleanup_requested',v_key,'pending',clock_timestamp(),8
    ) on conflict (owner_id,idempotency_key) do nothing;

    select count(*) into v_existing
    from public.media_asset_outbox e
    where e.owner_id=p_owner_id and e.asset_id=v_asset.id
      and e.operation_id=p_operation_id
      and e.event_type='media_cleanup_requested'
      and e.idempotency_key=v_key;
    if v_existing <> 1 then
      raise exception 'character cleanup idempotency conflict' using errcode='23505';
    end if;
    v_count := v_count + 1;
  end loop;

  return jsonb_build_object(
    'character_id',p_character_id,
    'owner_id',p_owner_id,
    'operation_id',p_operation_id,
    'assets_enqueued',v_count,
    'status',case when v_count=0 then 'ready_to_finalize' else 'cleanup_pending' end
  );
end;
$$;

-- One cleanup event per claim. Re-check exact references before returning a
-- Storage key. Dead-letter referenced objects instead of deleting them.
create or replace function public.pwa_claim_media_cleanup(
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
  if p_claim_token is null or p_lease_seconds is null
     or p_lease_seconds < 10 or p_lease_seconds > 900 then
    raise exception 'invalid media cleanup claim' using errcode='22023';
  end if;

  update public.media_asset_outbox
  set status='dead_letter',claim_token=null,claim_expires_at=null
  where event_type='media_cleanup_requested'
    and status='claimed' and claim_expires_at <= clock_timestamp()
    and attempts >= max_attempts;

  select * into v_event
  from public.media_asset_outbox e
  where e.event_type='media_cleanup_requested'
    and (
      (e.status='pending' and e.available_at <= clock_timestamp() and e.attempts < e.max_attempts)
      or (e.status='claimed' and e.claim_expires_at <= clock_timestamp() and e.attempts < e.max_attempts)
    )
  order by e.available_at,e.created_at
  limit 1
  for update skip locked;

  if not found then
    return null;
  end if;

  select * into v_asset
  from public.media_assets a
  where a.id=v_event.asset_id and a.owner_id=v_event.owner_id
  for update;
  if not found or v_asset.status <> 'cleanup_pending'
     or v_asset.character_id is null
     or v_asset.bucket <> 'studio-media'
     or v_asset.storage_path is null
     or not exists (
       select 1 from public.characters c
       where c.id=v_asset.character_id and c.owner_id=v_asset.owner_id
         and c.cleanup_operation_id=v_event.operation_id
     ) then
    update public.media_asset_outbox
    set status='dead_letter',claim_token=null,claim_expires_at=null
    where id=v_event.id;
    return null;
  end if;

  if exists (
    select 1 from public.media_assets other
    where other.id <> v_asset.id
      and other.bucket=v_asset.bucket
      and other.storage_path=v_asset.storage_path
      and other.status <> 'deleted'
  ) or exists (
    select 1 from public.media_assets other
    where other.id <> v_asset.id
      and position(v_asset.storage_path in coalesce(other.metadata::text,'')) > 0
      and other.status <> 'deleted'
  ) or exists (
    select 1 from public.characters other_character
    where (v_asset.character_id is null or other_character.id <> v_asset.character_id)
      and other_character.owner_id=v_asset.owner_id
      and (
        position(v_asset.storage_path in coalesce(other_character.reference_data::text,'')) > 0
        or position(v_asset.storage_path in coalesce(other_character.avatar_url,'')) > 0
      )
  ) then
    update public.media_asset_outbox
    set status='dead_letter',claim_token=null,claim_expires_at=null
    where id=v_event.id;
    return null;
  end if;

  update public.media_asset_outbox
  set status='claimed',claim_token=p_claim_token,
      claim_expires_at=clock_timestamp() + make_interval(secs => p_lease_seconds),
      attempts=attempts+1
  where id=v_event.id
  returning * into v_event;

  return jsonb_build_object(
    'event_id',v_event.id,'owner_id',v_event.owner_id,'asset_id',v_asset.id,
    'character_id',v_asset.character_id,'claim_token',p_claim_token,'attempts',v_event.attempts,
    'max_attempts',v_event.max_attempts,
    'bucket',v_asset.bucket,'storage_path',v_asset.storage_path
  );
end;
$$;

-- Storage DELETE is outside Postgres. This transaction finalizes the tombstone
-- and event only after the worker confirms DELETE or a 404 (already absent).
create or replace function public.pwa_complete_media_cleanup(
  p_owner_id uuid,
  p_asset_id uuid,
  p_event_id uuid,
  p_claim_token uuid
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_event public.media_asset_outbox%rowtype;
  v_asset public.media_assets%rowtype;
begin
  if p_owner_id is null or p_asset_id is null or p_event_id is null or p_claim_token is null then
    raise exception 'invalid media cleanup completion' using errcode='22023';
  end if;

  select * into v_event
  from public.media_asset_outbox
  where id=p_event_id and owner_id=p_owner_id and asset_id=p_asset_id
    and event_type='media_cleanup_requested'
    and status='claimed' and claim_token=p_claim_token
    and claim_expires_at > clock_timestamp()
  for update;
  if not found then
    raise exception 'media cleanup claim is stale' using errcode='P0002';
  end if;

  select * into v_asset
  from public.media_assets
  where id=p_asset_id and owner_id=p_owner_id and status='cleanup_pending'
  for update;
  if not found or v_asset.character_id is null or not exists (
    select 1 from public.characters c
    where c.id=v_asset.character_id and c.owner_id=p_owner_id
      and c.cleanup_operation_id=v_event.operation_id
  ) then
    raise exception 'media cleanup asset is no longer pending for this operation'
      using errcode='P0002';
  end if;

  update public.media_assets
  set status='deleted',character_id=null,version=version+1
  where id=p_asset_id and owner_id=p_owner_id and status='cleanup_pending'
  returning * into v_asset;
  if not found then
    raise exception 'media cleanup asset finalization was lost' using errcode='P0002';
  end if;

  update public.media_asset_outbox
  set status='delivered',claim_token=null,claim_expires_at=null,
      delivered_at=clock_timestamp()
  where id=p_event_id and owner_id=p_owner_id and asset_id=p_asset_id
    and event_type='media_cleanup_requested'
    and status='claimed' and claim_token=p_claim_token;
  if not found then
    raise exception 'media cleanup claim was lost' using errcode='P0002';
  end if;

  return jsonb_build_object('id',v_asset.id,'status',v_asset.status,'version',v_asset.version);
end;
$$;

create or replace function public.pwa_retry_media_cleanup(
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
begin
  if p_owner_id is null or p_asset_id is null or p_event_id is null or p_claim_token is null
     or p_retry_delay_seconds is null or p_retry_delay_seconds < 1
     or p_retry_delay_seconds > 86400 then
    raise exception 'invalid media cleanup retry delay' using errcode='22023';
  end if;

  select * into v_event
  from public.media_asset_outbox
  where id=p_event_id and owner_id=p_owner_id and asset_id=p_asset_id
    and event_type='media_cleanup_requested'
    and status='claimed' and claim_token=p_claim_token
    and claim_expires_at > clock_timestamp()
  for update;
  if not found then
    raise exception 'media cleanup claim is stale' using errcode='P0002';
  end if;

  if v_event.attempts >= v_event.max_attempts then
    update public.media_asset_outbox
    set status='dead_letter',claim_token=null,claim_expires_at=null
    where id=p_event_id and owner_id=p_owner_id and asset_id=p_asset_id
      and event_type='media_cleanup_requested' and claim_token=p_claim_token;
  else
    update public.media_asset_outbox
    set status='pending',
        available_at=clock_timestamp() + make_interval(secs => p_retry_delay_seconds),
        claim_token=null,claim_expires_at=null
    where id=p_event_id and owner_id=p_owner_id and asset_id=p_asset_id
      and event_type='media_cleanup_requested' and claim_token=p_claim_token;
  end if;

  return jsonb_build_object(
    'event_status',case when v_event.attempts >= v_event.max_attempts then 'dead_letter' else 'pending' end,
    'asset_status','cleanup_pending'
  );
end;
$$;

-- Final character removal is deliberately separate and succeeds only when no
-- associated media rows remain. Tombstone rows remain detached for audit.
create or replace function public.pwa_finalize_character_media_cleanup(
  p_owner_id uuid,
  p_character_id uuid
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_deleted uuid;
  v_cleanup_operation_id uuid;
begin
  if p_owner_id is null or p_character_id is null then
    raise exception 'invalid character finalization' using errcode='22023';
  end if;

  select cleanup_operation_id into v_cleanup_operation_id
  from public.characters
  where id=p_character_id and owner_id=p_owner_id
  for update;
  if not found then
    raise exception 'character not found' using errcode='P0002';
  end if;
  if v_cleanup_operation_id is null then
    raise exception 'character cleanup was not requested' using errcode='23514';
  end if;

  if exists (
    select 1 from public.media_assets
    where owner_id=p_owner_id and character_id=p_character_id
  ) then
    raise exception 'character still has media assets awaiting cleanup' using errcode='23514';
  end if;

  delete from public.characters
  where id=p_character_id and owner_id=p_owner_id
  returning id into v_deleted;
  if v_deleted is null then
    raise exception 'character not found' using errcode='P0002';
  end if;

  return jsonb_build_object('character_id',v_deleted,'status','deleted');
end;
$$;

revoke all on function public.pwa_request_character_media_cleanup(uuid,uuid,uuid)
  from public,anon,authenticated;
revoke all on function public.pwa_claim_media_cleanup(uuid,integer)
  from public,anon,authenticated;
revoke all on function public.pwa_complete_media_cleanup(uuid,uuid,uuid,uuid)
  from public,anon,authenticated;
revoke all on function public.pwa_retry_media_cleanup(uuid,uuid,uuid,uuid,integer)
  from public,anon,authenticated;
revoke all on function public.pwa_finalize_character_media_cleanup(uuid,uuid)
  from public,anon,authenticated;

grant execute on function public.pwa_request_character_media_cleanup(uuid,uuid,uuid) to service_role;
grant execute on function public.pwa_claim_media_cleanup(uuid,integer) to service_role;
grant execute on function public.pwa_complete_media_cleanup(uuid,uuid,uuid,uuid) to service_role;
grant execute on function public.pwa_retry_media_cleanup(uuid,uuid,uuid,uuid,integer) to service_role;
grant execute on function public.pwa_finalize_character_media_cleanup(uuid,uuid) to service_role;

comment on function public.pwa_request_character_media_cleanup(uuid,uuid,uuid) is
  'Owner-scoped atomic character media tombstone + cleanup outbox reservation; service_role only.';
comment on function public.pwa_claim_media_cleanup(uuid,integer) is
  'Claims one private media cleanup event with a lease and fencing token; service_role only.';
comment on function public.pwa_complete_media_cleanup(uuid,uuid,uuid,uuid) is
  'Fenced atomic media tombstone finalization and cleanup event acknowledgement; service_role only.';
comment on function public.pwa_finalize_character_media_cleanup(uuid,uuid) is
  'Deletes an owner-matched character only after every associated media row is detached; service_role only.';
