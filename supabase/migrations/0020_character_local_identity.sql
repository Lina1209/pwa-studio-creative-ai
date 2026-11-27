-- PWA Studio: durable owner-scoped local-to-cloud character identity.
-- DRAFT ONLY. Apply only in disposable PostgreSQL/Supabase test environments.
-- Never apply to production without a separately approved migration review.

alter table public.characters
  add column if not exists source_local_id uuid;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid='public.characters'::regclass
      and conname='characters_owner_source_local_unique'
  ) then
    alter table public.characters
      add constraint characters_owner_source_local_unique
      unique (owner_id, source_local_id);
  end if;
end
$$;

comment on column public.characters.source_local_id is
  'Stable browser-local character UUID used only for owner-scoped idempotent cloud import; never the cloud primary key.';

-- Character writes must pass through the authenticated server API. The
-- service-role credential remains server-only; browsers retain owner-scoped
-- reads but cannot bypass the idempotent create or cleanup lifecycle.
revoke insert, update, delete on public.characters from public, anon, authenticated;
grant select on public.characters to authenticated, service_role;
grant select, insert, update on public.characters to service_role;

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
    'created_at',v_character.created_at
  );
end;
$$;

revoke all on function public.pwa_create_character_idempotent(uuid,uuid,text,text,jsonb)
  from public, anon, authenticated;
grant execute on function public.pwa_create_character_idempotent(uuid,uuid,text,text,jsonb)
  to service_role;
