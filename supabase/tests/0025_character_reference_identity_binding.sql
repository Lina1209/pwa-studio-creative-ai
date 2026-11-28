-- Disposable integration test for explicit local-reference/media-asset identity.
-- Run after migration 0025 in throwaway PostgreSQL only.
\set ON_ERROR_STOP on
begin;
select set_config('request.jwt.claim.role','service_role',true);
select set_config('pwa.test_owner_id', :'PWA_TEST_OWNER_ID', true);

do $$
declare
  v_owner uuid := current_setting('pwa.test_owner_id')::uuid;
  v_other_owner uuid := gen_random_uuid();
  v_local_character uuid := gen_random_uuid();
  v_local_reference text;
  v_other_reference text;
  v_character jsonb;
  v_foreign_character jsonb;
  v_asset uuid := gen_random_uuid();
  v_operation uuid := gen_random_uuid();
  v_event uuid := gen_random_uuid();
  v_object uuid := gen_random_uuid();
  v_result jsonb;
  v_replay jsonb;
  v_conflict boolean := false;
  v_character_id uuid;
  v_storage_path text;
begin
  if not exists (select 1 from auth.users where id=v_owner) then
    raise exception 'PWA_TEST_OWNER_ID must identify an existing disposable auth user';
  end if;
  insert into auth.users(id,email) values (v_other_owner,'reference-binding-foreign@example.invalid');

  v_character := public.pwa_create_character_idempotent(
    v_owner,v_local_character,'Reference binding test',null,'{"references":[{"id":"placeholder"}]}'::jsonb
  );
  v_character_id := (v_character->>'id')::uuid;
  v_local_reference := v_character_id::text || '-' || gen_random_uuid()::text;
  v_other_reference := v_character_id::text || '-' || gen_random_uuid()::text;
  v_foreign_character := public.pwa_create_character_idempotent(
    v_other_owner,gen_random_uuid(),'Foreign character',null,'{}'::jsonb
  );

  v_storage_path := v_owner::text || '/characters/' || v_character_id::text || '/' || v_object::text || '.png';
  v_result := public.pwa_reserve_character_reference_upload_v2(
    v_owner,v_character_id,v_local_reference,v_asset,v_operation,v_event,
    'reference-binding-idempotency-001','hero.png','image/png','studio-media',
    v_storage_path,128,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',16,8
  );
  v_replay := public.pwa_reserve_character_reference_upload_v2(
    v_owner,v_character_id,v_local_reference,v_asset,v_operation,v_event,
    'reference-binding-idempotency-001','hero.png','image/png','studio-media',
    v_storage_path,128,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',16,8
  );
  if v_result->>'id' is distinct from v_asset::text
     or v_result->>'local_reference_id' is distinct from v_local_reference::text
     or v_replay->>'local_reference_id' is distinct from v_local_reference::text then
    raise exception 'exact retry did not preserve the explicit reference-to-asset mapping';
  end if;

  if (select count(*) from public.media_assets
      where id=v_asset and owner_id=v_owner and character_id=v_character_id
        and local_reference_id=v_local_reference) <> 1 then
    raise exception 'media asset does not retain the expected owner/character/local-reference tuple';
  end if;

  -- A local reference UUID cannot be rebound to a second asset in the same
  -- owner+character namespace.
  v_conflict := false;
  begin
    perform public.pwa_reserve_character_reference_upload_v2(
      v_owner,v_character_id,v_local_reference::text,gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),
      'reference-binding-idempotency-002','other.png','image/png','studio-media',
      v_owner::text || '/characters/' || v_character_id::text || '/' || gen_random_uuid()::text || '.png',
      128,'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',16,8
    );
  exception when unique_violation then
    v_conflict := true;
  end;
  if not v_conflict then
    raise exception 'duplicate local reference binding was not rejected';
  end if;

  -- Replaying the same asset/idempotency with a different local reference
  -- must not silently change its established identity.
  v_conflict := false;
  begin
    perform public.pwa_reserve_character_reference_upload_v2(
      v_owner,v_character_id,v_other_reference,v_asset,v_operation,v_event,
      'reference-binding-idempotency-001','hero.png','image/png','studio-media',
      v_storage_path,128,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',16,8
    );
  exception when unique_violation then
    v_conflict := true;
  end;
  if not v_conflict then
    raise exception 'existing asset was silently rebound to a different local reference ID';
  end if;

  -- Foreign character IDs cannot be used with the authenticated owner's ID.
  v_conflict := false;
  begin
    perform public.pwa_reserve_character_reference_upload_v2(
      v_owner,(v_foreign_character->>'id')::uuid,gen_random_uuid()::text,
      gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),
      'reference-binding-foreign-character','foreign.png','image/png','studio-media',
      v_owner::text || '/characters/' || (v_foreign_character->>'id') || '/' || gen_random_uuid()::text || '.png',
      128,'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',16,8
    );
  exception when sqlstate 'P0002' then
    v_conflict := true;
  end;
  if not v_conflict then
    raise exception 'foreign character association was not rejected';
  end if;

  if has_function_privilege('authenticated',
       'public.pwa_reserve_character_reference_upload_v2(uuid,uuid,text,uuid,uuid,uuid,text,text,text,text,text,bigint,text,integer,integer)','EXECUTE') then
    raise exception 'authenticated role can execute the server-only reference-binding RPC';
  end if;
  if not has_function_privilege('service_role',
       'public.pwa_reserve_character_reference_upload_v2(uuid,uuid,text,uuid,uuid,uuid,text,text,text,text,text,bigint,text,integer,integer)','EXECUTE') then
    raise exception 'service_role cannot execute the reference-binding RPC';
  end if;
end;
$$;
rollback;
