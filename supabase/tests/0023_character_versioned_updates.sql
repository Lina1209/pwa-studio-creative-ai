-- Disposable behavior tests for migration 0023. Never run against production.
\set ON_ERROR_STOP on
begin;
select set_config('request.jwt.claim.role','service_role',true);
select set_config('pwa.test_owner_id', :'PWA_TEST_OWNER_ID', true);

do $$
declare
  v_owner uuid := current_setting('pwa.test_owner_id')::uuid;
  v_other uuid := gen_random_uuid();
  v_local uuid := gen_random_uuid();
  v_created jsonb;
  v_updated jsonb;
  v_stale jsonb;
  v_foreign jsonb;
begin
  if not exists (select 1 from auth.users where id=v_owner) then
    raise exception 'PWA_TEST_OWNER_ID must identify an existing disposable auth user';
  end if;
  insert into auth.users(id,email) values (v_other,'character-version-foreign@example.invalid');

  v_created := public.pwa_create_character_idempotent(
    v_owner,v_local,'Versioned passport',null,'{"kind":"person"}'::jsonb
  );
  if (select version from public.characters where id=(v_created->>'id')::uuid) <> 1 then
    raise exception 'new character version must start at 1';
  end if;

  v_updated := public.pwa_update_character_versioned(
    v_owner,(v_created->>'id')::uuid,1,'{"name":"Updated passport"}'::jsonb
  );
  if v_updated->>'version' <> '2' or v_updated->>'name' <> 'Updated passport' then
    raise exception 'valid compare-and-swap did not update exactly once';
  end if;

  v_stale := public.pwa_update_character_versioned(
    v_owner,(v_created->>'id')::uuid,1,'{"name":"Stale overwrite"}'::jsonb
  );
  if v_stale->>'conflict' <> 'true' or v_stale->>'version' <> '2' then
    raise exception 'stale expected version did not return conflict';
  end if;
  if (select name from public.characters where id=(v_created->>'id')::uuid) <> 'Updated passport'
     or (select version from public.characters where id=(v_created->>'id')::uuid) <> 2 then
    raise exception 'stale update changed data or version';
  end if;

  v_foreign := public.pwa_update_character_versioned(
    v_other,(v_created->>'id')::uuid,2,'{"name":"Cross-owner overwrite"}'::jsonb
  );
  if v_foreign->>'not_found' <> 'true' then
    raise exception 'foreign owner update did not return indistinguishable not-found';
  end if;

  begin
    perform public.pwa_update_character_versioned(
      v_owner,(v_created->>'id')::uuid,2,jsonb_build_object('owner_id',v_other::text)
    );
    raise exception 'unexpected field was accepted';
  exception when sqlstate '22023' then
    null;
  end;

  if has_function_privilege('authenticated',
       'public.pwa_update_character_versioned(uuid,uuid,bigint,jsonb)','EXECUTE')
     or has_function_privilege('anon',
       'public.pwa_update_character_versioned(uuid,uuid,bigint,jsonb)','EXECUTE') then
    raise exception 'browser role can execute server-only update RPC';
  end if;
  if not has_function_privilege('service_role',
       'public.pwa_update_character_versioned(uuid,uuid,bigint,jsonb)','EXECUTE') then
    raise exception 'service_role cannot execute versioned update RPC';
  end if;
  if has_table_privilege('authenticated','public.characters','UPDATE') then
    raise exception 'authenticated role can bypass versioned update RPC';
  end if;
  if not exists (
    select 1 from pg_indexes
    where schemaname='public' and tablename='characters'
      and indexname='characters_owner_created_id_desc_idx'
  ) then
    raise exception 'character keyset pagination index is missing';
  end if;
end;
$$;
rollback;
