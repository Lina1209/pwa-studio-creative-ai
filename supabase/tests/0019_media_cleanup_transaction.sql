-- Disposable-database transaction harness for migration 0019.
-- Run ONLY against a disposable Supabase/Postgres database with migrations
-- 0005, 0012, 0017, 0018, and 0019 applied.
--
-- Required:
--   PWA_TEST_OWNER_ID=<existing auth.users UUID>
-- Example:
--   psql "$DISPOSABLE_DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -v PWA_TEST_OWNER_ID="$PWA_TEST_OWNER_ID" \
--     -f supabase/tests/0019_media_cleanup_transaction.sql
--
-- This harness simulates a successful Storage delete by calling the completion
-- RPC. It does not contact Storage. All database fixtures roll back.

\set ON_ERROR_STOP on
begin;
select set_config('pwa.test_owner_id', :'PWA_TEST_OWNER_ID', true);

do $$
declare
  v_owner uuid := current_setting('pwa.test_owner_id')::uuid;
  v_character uuid := gen_random_uuid();
  v_asset uuid := gen_random_uuid();
  v_object uuid := gen_random_uuid();
  v_operation uuid := gen_random_uuid();
  v_token_a uuid := gen_random_uuid();
  v_token_b uuid := gen_random_uuid();
  v_path text;
  v_request jsonb;
  v_claim_a jsonb;
  v_claim_b jsonb;
  v_final jsonb;
  v_status text;
  v_character_exists boolean;
begin
  if not exists (select 1 from auth.users where id=v_owner) then
    raise exception 'PWA_TEST_OWNER_ID must identify an existing disposable auth user';
  end if;

  insert into public.characters(id,owner_id,name,reference_data)
  values (v_character,v_owner,'Disposable cleanup harness','{}'::jsonb);

  v_path := v_owner::text || '/characters/' || v_character::text || '/' || v_object::text || '.png';
  insert into public.media_assets(
    id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
    metadata,version,operation_id,size_bytes,content_sha256,width,height
  ) values (
    v_asset,v_owner,v_character,'fixture.png','image/png','studio-media','ready',v_path,
    '{"source":"disposable-cleanup-test"}'::jsonb,1,v_operation,128,
    repeat('a',64),8,8
  );

  v_request := public.pwa_request_character_media_cleanup(v_owner,v_character,v_operation);
  if (v_request->>'assets_enqueued')::integer <> 1
     or v_request->>'status' <> 'cleanup_pending' then
    raise exception 'cleanup reservation did not enqueue exactly one asset: %',v_request;
  end if;

  -- Same operation is idempotent and must not create a second event.
  v_request := public.pwa_request_character_media_cleanup(v_owner,v_character,v_operation);
  if (select count(*) from public.media_asset_outbox
      where owner_id=v_owner and asset_id=v_asset
        and operation_id=v_operation and event_type='media_cleanup_requested') <> 1 then
    raise exception 'cleanup reservation created duplicate outbox events';
  end if;

  v_claim_a := public.pwa_claim_media_cleanup(v_token_a,120);
  if v_claim_a is null or v_claim_a->>'asset_id' <> v_asset::text then
    raise exception 'first cleanup worker failed to claim fixture';
  end if;

  update public.media_asset_outbox
  set claim_expires_at=clock_timestamp()-interval '1 second'
  where id=(v_claim_a->>'event_id')::uuid and claim_token=v_token_a;

  v_claim_b := public.pwa_claim_media_cleanup(v_token_b,120);
  if v_claim_b is null or v_claim_b->>'asset_id' <> v_asset::text
     or v_claim_b->>'claim_token' <> v_token_b::text
     or (v_claim_b->>'attempts')::integer <> 2 then
    raise exception 'second worker did not reclaim with a fresh fencing token';
  end if;

  begin
    perform public.pwa_complete_media_cleanup(
      v_owner,v_asset,(v_claim_a->>'event_id')::uuid,v_token_a
    );
    raise exception 'stale worker A unexpectedly completed cleanup';
  exception when sqlstate 'P0002' then
    null;
  end;

  begin
    perform public.pwa_retry_media_cleanup(
      v_owner,v_asset,(v_claim_a->>'event_id')::uuid,v_token_a,30
    );
    raise exception 'stale worker A unexpectedly scheduled retry';
  exception when sqlstate 'P0002' then
    null;
  end;

  -- Represents a Storage DELETE success/404; actual Storage is not contacted.
  perform public.pwa_complete_media_cleanup(
    v_owner,v_asset,(v_claim_b->>'event_id')::uuid,v_token_b
  );

  select status into v_status from public.media_assets where id=v_asset and owner_id=v_owner;
  if v_status <> 'deleted' then
    raise exception 'media tombstone was not finalized';
  end if;
  if exists (select 1 from public.media_assets where id=v_asset and character_id is not null) then
    raise exception 'deleted media tombstone remains attached to character';
  end if;
  if not exists (
    select 1 from public.media_asset_outbox
    where id=(v_claim_b->>'event_id')::uuid and status='delivered'
      and claim_token is null and claim_expires_at is null
  ) then
    raise exception 'cleanup event was not atomically acknowledged';
  end if;

  v_final := public.pwa_finalize_character_media_cleanup(v_owner,v_character);
  if v_final->>'status' <> 'deleted' then
    raise exception 'character finalization failed';
  end if;
  select exists(select 1 from public.characters where id=v_character) into v_character_exists;
  if v_character_exists then
    raise exception 'character row still exists after finalization';
  end if;
end;
$$;

rollback;
