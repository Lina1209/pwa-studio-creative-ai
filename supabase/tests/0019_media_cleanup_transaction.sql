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
  v_busy_character uuid := gen_random_uuid();
  v_busy_asset uuid := gen_random_uuid();
  v_unindexed_character uuid := gen_random_uuid();
  v_referenced_character uuid := gen_random_uuid();
  v_referencing_asset uuid := gen_random_uuid();
  v_referenced_asset uuid := gen_random_uuid();
  v_referenced_path text;
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

  -- Simulate an authenticated JWT role and prove it cannot set the
  -- server-managed deletion intent even when SQL privileges are elevated.
  perform set_config('request.jwt.claim.role','authenticated',true);
  begin
    update public.characters
    set cleanup_operation_id=gen_random_uuid(),cleanup_requested_at=clock_timestamp()
    where id=v_character and owner_id=v_owner;
    raise exception 'browser role unexpectedly changed cleanup intent';
  exception when sqlstate '42501' then
    null;
  end;
  perform set_config('request.jwt.claim.role','service_role',true);

  v_request := public.pwa_request_character_media_cleanup(v_owner,v_character,v_operation);
  if (v_request->>'assets_enqueued')::integer <> 1
     or v_request->>'status' <> 'cleanup_pending' then
    raise exception 'cleanup reservation did not enqueue exactly one asset: %',v_request;
  end if;

  -- The browser role cannot forge, update, or delete server-managed media rows.
  if has_table_privilege('authenticated','public.media_assets','INSERT')
     or has_table_privilege('authenticated','public.media_assets','UPDATE')
     or has_table_privilege('authenticated','public.media_assets','DELETE')
     or has_table_privilege('authenticated','public.characters','DELETE') then
    raise exception 'browser role retains an unsafe media/character write privilege';
  end if;

  -- A late upload reservation is blocked by the character deletion marker.
  begin
    perform public.pwa_reserve_character_reference_upload(
      v_owner,v_character,gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),
      'late-upload-' || gen_random_uuid()::text,'late.png','image/png',
      'studio-media',
      v_owner::text || '/characters/' || v_character::text || '/' || gen_random_uuid()::text || '.png',
      128,repeat('b',64),8,8
    );
    raise exception 'late media upload unexpectedly succeeded';
  exception when sqlstate '23514' then
    null;
  end;

  -- Same operation is idempotent and must not create a second event.
  v_request := public.pwa_request_character_media_cleanup(v_owner,v_character,v_operation);
  if (select count(*) from public.media_asset_outbox
      where owner_id=v_owner and asset_id=v_asset
        and operation_id=v_operation and event_type='media_cleanup_requested') <> 1 then
    raise exception 'cleanup reservation created duplicate outbox events';
  end if;

  -- A private object path embedded in a passport without a matching media
  -- row is ambiguous; do not delete the character and orphan the object.
  insert into public.characters(id,owner_id,name,reference_data)
  values (
    v_unindexed_character,v_owner,'Unindexed path fixture',
    jsonb_build_object(
      'reference',
      v_owner::text || '/characters/' || v_unindexed_character::text || '/' ||
      gen_random_uuid()::text || '.png'
    )
  );
  begin
    perform public.pwa_request_character_media_cleanup(
      v_owner,v_unindexed_character,gen_random_uuid()
    );
    raise exception 'cleanup unexpectedly accepted an unindexed passport path';
  exception when sqlstate '23514' then
    null;
  end;
  if (select cleanup_operation_id from public.characters where id=v_unindexed_character) is not null then
    raise exception 'unindexed passport path rejection did not roll back deletion intent';
  end if;

  -- A different media row's JSON metadata is also a live reference.
  -- Cleanup must fail closed rather than deleting an object still referenced
  -- outside the character's own passport.
  insert into public.characters(id,owner_id,name,reference_data)
  values (v_referenced_character,v_owner,'Metadata reference fixture','{}'::jsonb);
  v_referenced_path := v_owner::text || '/characters/' || v_referenced_character::text || '/' ||
    gen_random_uuid()::text || '.png';
  insert into public.media_assets(
    id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
    metadata,version,operation_id,size_bytes,content_sha256,width,height
  ) values (
    v_referenced_asset,v_owner,v_referenced_character,'target.png','image/png',
    'studio-media','ready',v_referenced_path,'{}'::jsonb,1,gen_random_uuid(),
    128,repeat('d',64),8,8
  );
  insert into public.media_assets(
    id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
    metadata,version,operation_id,size_bytes,content_sha256,width,height
  ) values (
    v_referencing_asset,v_owner,null,'pointer.json','application/json',
    'studio-media','ready',
    v_owner::text || '/misc/' || gen_random_uuid()::text || '.png',
    jsonb_build_object('linked_object',v_referenced_path),1,gen_random_uuid(),
    128,repeat('e',64),8,8
  );
  begin
    perform public.pwa_request_character_media_cleanup(
      v_owner,v_referenced_character,gen_random_uuid()
    );
    raise exception 'cleanup unexpectedly accepted an external metadata reference';
  exception when sqlstate '23514' then
    null;
  end;
  if (select cleanup_operation_id from public.characters where id=v_referenced_character) is not null
     or (select status from public.media_assets where id=v_referenced_asset) <> 'ready' then
    raise exception 'metadata-reference rejection did not roll back cleanup reservation';
  end if;

  -- A character with an upload still in flight cannot enter cleanup. The
  -- failed reservation must roll back its deletion-intent marker.
  insert into public.characters(id,owner_id,name,reference_data)
  values (v_busy_character,v_owner,'Busy upload fixture','{}'::jsonb);
  insert into public.media_assets(
    id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
    metadata,version,operation_id,size_bytes,content_sha256,width,height
  ) values (
    v_busy_asset,v_owner,v_busy_character,'busy.png','image/png','studio-media','pending_upload',
    v_owner::text || '/characters/' || v_busy_character::text || '/' || gen_random_uuid()::text || '.png',
    '{}'::jsonb,1,gen_random_uuid(),128,repeat('c',64),8,8
  );
  begin
    perform public.pwa_request_character_media_cleanup(v_owner,v_busy_character,gen_random_uuid());
    raise exception 'cleanup unexpectedly raced an in-flight upload';
  exception when sqlstate '23514' then
    null;
  end;
  if (select cleanup_operation_id from public.characters where id=v_busy_character) is not null
     or (select status from public.media_assets where id=v_busy_asset) <> 'pending_upload' then
    raise exception 'failed in-flight-upload cleanup reservation did not roll back';
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
