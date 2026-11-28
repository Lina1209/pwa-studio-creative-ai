-- Disposable behavior test for migration 0020.
-- Run only in CI/local throwaway PostgreSQL after migrations 0012, 0017–0020.
\set ON_ERROR_STOP on
begin;
select set_config('request.jwt.claim.role','service_role',true);
select set_config('pwa.test_owner_id', :'PWA_TEST_OWNER_ID', true);

do $$
declare
  v_owner uuid := current_setting('pwa.test_owner_id')::uuid;
  v_other_owner uuid := gen_random_uuid();
  v_local_id uuid := gen_random_uuid();
  v_first jsonb;
  v_replay jsonb;
  v_foreign jsonb;
  v_conflict boolean := false;
begin
  if not exists (select 1 from auth.users where id=v_owner) then
    raise exception 'PWA_TEST_OWNER_ID must identify an existing disposable auth user';
  end if;
  insert into auth.users(id,email) values (v_other_owner,'character-idempotency-foreign@example.invalid');

  v_first := public.pwa_create_character_idempotent(
    v_owner,v_local_id,'Stable local passport','description','{"kind":"person","face":"green eyes"}'::jsonb
  );
  v_replay := public.pwa_create_character_idempotent(
    v_owner,v_local_id,'Stable local passport','description','{"kind":"person","face":"green eyes"}'::jsonb
  );
  if v_first->>'id' is distinct from v_replay->>'id'
     or v_first->>'source_local_id' is distinct from v_local_id::text then
    raise exception 'an exact replay did not return the original cloud mapping';
  end if;
  if (select count(*) from public.characters
      where owner_id=v_owner and source_local_id=v_local_id) <> 1 then
    raise exception 'an exact replay created duplicate character rows';
  end if;

  begin
    perform public.pwa_create_character_idempotent(
      v_owner,v_local_id,'Changed name','description','{"kind":"person","face":"green eyes"}'::jsonb
    );
  exception when sqlstate '23505' then
    v_conflict := true;
  end;
  if not v_conflict then
    raise exception 'reusing a local ID with changed content did not conflict';
  end if;
  if (select name from public.characters where owner_id=v_owner and source_local_id=v_local_id)
     <> 'Stable local passport' then
    raise exception 'conflicting replay overwrote the original passport';
  end if;

  -- The same browser UUID in a different account is a different mapping.
  v_foreign := public.pwa_create_character_idempotent(
    v_other_owner,v_local_id,'Other account passport',null,'{}'::jsonb
  );
  if v_foreign->>'id' is null or v_foreign->>'id'=v_first->>'id' then
    raise exception 'local UUID was not correctly scoped by owner';
  end if;

  if has_table_privilege('authenticated','public.characters','INSERT')
     or has_table_privilege('authenticated','public.characters','UPDATE')
     or has_table_privilege('authenticated','public.characters','DELETE') then
    raise exception 'authenticated browser role retains direct character write privileges';
  end if;
  if has_function_privilege('authenticated',
       'public.pwa_create_character_idempotent(uuid,uuid,text,text,jsonb)','EXECUTE') then
    raise exception 'authenticated browser role can execute the server-only idempotency RPC';
  end if;
  if not has_function_privilege('service_role',
       'public.pwa_create_character_idempotent(uuid,uuid,text,text,jsonb)','EXECUTE') then
    raise exception 'service_role cannot execute the character idempotency RPC';
  end if;
end;
$$;
rollback;
