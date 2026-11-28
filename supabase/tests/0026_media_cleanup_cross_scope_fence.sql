-- Disposable PostgreSQL test for the cross-scope media deletion fence.
-- Run only after migrations 0005, 0009, 0012-0014, 0017-0026 on disposable CI.
-- No Storage calls are made; all fixtures roll back.
\set ON_ERROR_STOP on
begin;
select set_config('pwa.test_owner_id', :'PWA_TEST_OWNER_ID', true);

do $$
declare
  v_owner uuid := current_setting('pwa.test_owner_id')::uuid;
  v_character_a uuid := gen_random_uuid();
  v_asset_a uuid := gen_random_uuid();
  v_path_a text;
  v_replacement_event_a uuid := gen_random_uuid();
  v_character_b uuid := gen_random_uuid();
  v_asset_b uuid := gen_random_uuid();
  v_path_b text;
  v_cleanup_event_b uuid;
  v_replacement_event_b uuid := gen_random_uuid();
  v_character_c uuid := gen_random_uuid();
  v_asset_c uuid := gen_random_uuid();
  v_path_c text;
  v_cleanup_event_c uuid;
  v_operation_a uuid := gen_random_uuid();
  v_operation_b uuid := gen_random_uuid();
  v_operation_c uuid := gen_random_uuid();
  v_conflict_seen boolean;
begin
  if not exists (select 1 from auth.users where id=v_owner) then
    raise exception 'PWA_TEST_OWNER_ID must identify a disposable auth user';
  end if;

  -- Ordering A: replacement reserves deletion first. A whole-character
  -- cleanup must fail atomically and leave its marker and asset untouched.
  insert into public.characters(id,owner_id,name,reference_data)
  values(v_character_a,v_owner,'Cross-scope replacement-first','{}'::jsonb);
  v_path_a := v_owner::text || '/characters/' || v_character_a::text || '/' ||
    v_asset_a::text || '.png';
  insert into public.media_assets(
    id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
    metadata,version,operation_id,size_bytes,content_sha256,width,height
  ) values (
    v_asset_a,v_owner,v_character_a,'a.png','image/png','studio-media','ready',
    v_path_a,'{}'::jsonb,1,v_operation_a,128,repeat('a',64),8,8
  );
  insert into public.media_asset_outbox(
    id,owner_id,asset_id,operation_id,event_type,idempotency_key,status
  ) values (
    v_replacement_event_a,v_owner,v_asset_a,v_operation_a,
    'media_reference_replacement_cleanup_requested',
    'replacement-first:' || v_asset_a::text,'pending'
  );

  v_conflict_seen := false;
  begin
    perform public.pwa_request_character_media_cleanup(
      v_owner,v_character_a,gen_random_uuid()
    );
  exception when unique_violation then
    v_conflict_seen := true;
  end;
  if not v_conflict_seen then
    raise exception 'whole-character cleanup bypassed an active replacement deletion event';
  end if;
  if (select cleanup_operation_id from public.characters where id=v_character_a) is not null
     or (select status from public.media_assets where id=v_asset_a) <> 'ready'
     or (select count(*) from public.media_asset_outbox
         where asset_id=v_asset_a and status in ('pending','claimed')
           and event_type in ('media_cleanup_requested','media_reference_replacement_cleanup_requested')) <> 1 then
    raise exception 'replacement-first conflict did not roll back the whole-character reservation';
  end if;

  -- Ordering B: whole-character cleanup reserves first. A replacement event
  -- for the same object must fail with a uniqueness conflict.
  insert into public.characters(id,owner_id,name,reference_data)
  values(v_character_b,v_owner,'Cross-scope character-first','{}'::jsonb);
  v_path_b := v_owner::text || '/characters/' || v_character_b::text || '/' ||
    v_asset_b::text || '.png';
  insert into public.media_assets(
    id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
    metadata,version,operation_id,size_bytes,content_sha256,width,height
  ) values (
    v_asset_b,v_owner,v_character_b,'b.png','image/png','studio-media','ready',
    v_path_b,'{}'::jsonb,1,v_operation_b,128,repeat('b',64),8,8
  );
  perform public.pwa_request_character_media_cleanup(v_owner,v_character_b,v_operation_b);
  select id into v_cleanup_event_b from public.media_asset_outbox
  where asset_id=v_asset_b and event_type='media_cleanup_requested'
    and status='pending';
  if v_cleanup_event_b is null then
    raise exception 'whole-character cleanup event was not created';
  end if;

  v_conflict_seen := false;
  begin
    insert into public.media_asset_outbox(
      id,owner_id,asset_id,operation_id,event_type,idempotency_key,status
    ) values (
      v_replacement_event_b,v_owner,v_asset_b,gen_random_uuid(),
      'media_reference_replacement_cleanup_requested',
      'replacement-second:' || v_asset_b::text,'pending'
    );
  exception when unique_violation then
    v_conflict_seen := true;
  end;
  if not v_conflict_seen then
    raise exception 'replacement event bypassed an active whole-character deletion event';
  end if;
  if (select count(*) from public.media_asset_outbox
      where asset_id=v_asset_b and status in ('pending','claimed')
        and event_type in ('media_cleanup_requested','media_reference_replacement_cleanup_requested')) <> 1 then
    raise exception 'character-first conflict left more than one active deletion authorization';
  end if;

  -- Terminal events remain auditable but do not block a later operation.
  insert into public.characters(id,owner_id,name,reference_data)
  values(v_character_c,v_owner,'Cross-scope terminal event','{}'::jsonb);
  v_path_c := v_owner::text || '/characters/' || v_character_c::text || '/' ||
    v_asset_c::text || '.png';
  insert into public.media_assets(
    id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
    metadata,version,operation_id,size_bytes,content_sha256,width,height
  ) values (
    v_asset_c,v_owner,v_character_c,'c.png','image/png','studio-media','ready',
    v_path_c,'{}'::jsonb,1,v_operation_c,128,repeat('c',64),8,8
  );
  perform public.pwa_request_character_media_cleanup(v_owner,v_character_c,v_operation_c);
  select id into v_cleanup_event_c from public.media_asset_outbox
  where asset_id=v_asset_c and event_type='media_cleanup_requested'
    and status='pending';
  update public.media_asset_outbox
  set status='delivered',delivered_at=clock_timestamp()
  where id=v_cleanup_event_c;
  insert into public.media_asset_outbox(
    id,owner_id,asset_id,operation_id,event_type,idempotency_key,status
  ) values (
    gen_random_uuid(),v_owner,v_asset_c,gen_random_uuid(),
    'media_reference_replacement_cleanup_requested',
    'replacement-after-terminal:' || v_asset_c::text,'pending'
  );
  if (select count(*) from public.media_asset_outbox
      where asset_id=v_asset_c and status in ('pending','claimed')
        and event_type in ('media_cleanup_requested','media_reference_replacement_cleanup_requested')) <> 1 then
    raise exception 'terminal cleanup event incorrectly blocked a later operation';
  end if;
end;
$$;

rollback;
