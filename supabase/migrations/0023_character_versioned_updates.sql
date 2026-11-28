-- PWA Studio: versioned compare-and-swap updates for character passports.
-- Draft feature-branch migration. Apply only in disposable CI/local PostgreSQL.
-- Never apply to production without separate explicit approval.

alter table public.characters
  add column if not exists version bigint not null default 1;

alter table public.characters
  drop constraint if exists characters_version_positive;
alter table public.characters
  add constraint characters_version_positive check (version > 0);

create or replace function public.pwa_update_character_versioned(
  p_owner_id uuid,
  p_character_id uuid,
  p_expected_version bigint,
  p_changes jsonb
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_character public.characters%rowtype;
  v_name text;
  v_description text;
  v_reference_data jsonb;
begin
  if p_owner_id is null or p_character_id is null
     or p_expected_version is null or p_expected_version < 1
     or p_changes is null or jsonb_typeof(p_changes) <> 'object'
     or p_changes = '{}'::jsonb
     or exists (
       select 1 from jsonb_object_keys(p_changes) as keys(key)
       where key not in ('name','description','reference_data')
     ) then
    raise exception 'invalid character update request' using errcode='22023';
  end if;

  if p_changes ? 'name' then
    if jsonb_typeof(p_changes->'name') <> 'string' then
      raise exception 'character name must be text' using errcode='22023';
    end if;
    v_name := btrim(p_changes->>'name');
    if length(v_name) not between 1 and 120 then
      raise exception 'character name length is invalid' using errcode='22023';
    end if;
  end if;

  if p_changes ? 'description' then
    if jsonb_typeof(p_changes->'description') not in ('string','null') then
      raise exception 'character description must be text or null' using errcode='22023';
    end if;
    v_description := nullif(btrim(p_changes->>'description'),'');
    if v_description is not null and length(v_description) > 5000 then
      raise exception 'character description is too long' using errcode='22023';
    end if;
  end if;

  if p_changes ? 'reference_data' then
    if jsonb_typeof(p_changes->'reference_data') <> 'object'
       or octet_length(convert_to((p_changes->'reference_data')::text,'UTF8')) > 24576 then
      raise exception 'character reference data is invalid' using errcode='22023';
    end if;
  end if;

  select * into v_character
  from public.characters
  where id=p_character_id and owner_id=p_owner_id
  for update;

  if not found then
    return jsonb_build_object('not_found',true);
  end if;

  if v_character.cleanup_operation_id is not null then
    raise exception 'character cleanup is already in progress' using errcode='23514';
  end if;

  if v_character.version <> p_expected_version then
    return jsonb_build_object('conflict',true,'version',v_character.version);
  end if;

  update public.characters
  set name = case when p_changes ? 'name' then v_name else name end,
      description = case when p_changes ? 'description' then v_description else description end,
      reference_data = case when p_changes ? 'reference_data' then p_changes->'reference_data' else reference_data end,
      version = version + 1
  where id=p_character_id and owner_id=p_owner_id
  returning * into v_character;

  return jsonb_build_object(
    'id',v_character.id,
    'owner_id',v_character.owner_id,
    'source_local_id',v_character.source_local_id,
    'name',v_character.name,
    'description',v_character.description,
    'reference_data',v_character.reference_data,
    'created_at',v_character.created_at,
    'version',v_character.version
  );
end;
$$;

revoke all on function public.pwa_update_character_versioned(uuid,uuid,bigint,jsonb)
  from public, anon, authenticated;
grant execute on function public.pwa_update_character_versioned(uuid,uuid,bigint,jsonb)
  to service_role;

comment on column public.characters.version is
  'Monotonic optimistic-concurrency version. Mutations must use pwa_update_character_versioned.';

-- Include the initial version in idempotent create responses so clients can
-- immediately perform a version-checked edit without a second round trip.
create or replace function public.pwa_create_character_idempotent(
  p_owner_id uuid,
  p_source_local_id uuid,
  p_name text,
  p_description text,
  p_reference_data jsonb
) returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_character public.characters%rowtype;
  v_name text := btrim(coalesce(p_name,''));
  v_description text := nullif(btrim(p_description),'');
begin
  if p_owner_id is null or p_source_local_id is null
     or length(v_name) not between 1 and 120
     or (v_description is not null and length(v_description) > 5000)
     or p_reference_data is null
     or jsonb_typeof(p_reference_data) <> 'object'
     or octet_length(convert_to(p_reference_data::text,'UTF8')) > 24576 then
    raise exception 'invalid character passport import payload' using errcode='22023';
  end if;

  insert into public.characters(owner_id,source_local_id,name,description,reference_data)
  values (p_owner_id,p_source_local_id,v_name,v_description,p_reference_data)
  on conflict (owner_id,source_local_id) do nothing
  returning * into v_character;

  if not found then
    select * into v_character
    from public.characters
    where owner_id=p_owner_id and source_local_id=p_source_local_id
    for update;
    if not found then
      raise exception 'character import mapping is temporarily unavailable' using errcode='40001';
    end if;
    if v_character.cleanup_operation_id is not null then
      raise exception 'character cleanup is already in progress' using errcode='23514';
    end if;
    if v_character.name is distinct from v_name
       or v_character.description is distinct from v_description
       or v_character.reference_data is distinct from p_reference_data then
      raise exception 'local character ID is already linked to different cloud data'
        using errcode='23505';
    end if;
  end if;

  return jsonb_build_object(
    'id',v_character.id,
    'owner_id',v_character.owner_id,
    'source_local_id',v_character.source_local_id,
    'name',v_character.name,
    'description',v_character.description,
    'reference_data',v_character.reference_data,
    'created_at',v_character.created_at,
    'version',v_character.version
  );
end;
$$;

revoke all on function public.pwa_create_character_idempotent(uuid,uuid,text,text,jsonb)
  from public, anon, authenticated;
grant execute on function public.pwa_create_character_idempotent(uuid,uuid,text,text,jsonb)
  to service_role;
