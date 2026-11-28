-- PWA Studio: explicit owner/character/local-reference -> cloud asset binding.
-- DRAFT ONLY. CI applies this to disposable PostgreSQL; never run on production
-- without a separate migration review and explicit approval.

alter table public.media_assets
  add column if not exists local_reference_id uuid;

alter table public.media_assets
  drop constraint if exists media_assets_local_reference_requires_character;
alter table public.media_assets
  add constraint media_assets_local_reference_requires_character
  check (local_reference_id is null or character_id is not null);

create unique index if not exists media_assets_owner_character_local_reference_unique
  on public.media_assets(owner_id, character_id, local_reference_id)
  where local_reference_id is not null;

comment on column public.media_assets.local_reference_id is
  'Explicit browser-local reference UUID bound to this private cloud asset and character; NULL only for legacy/unmapped assets.';

-- Versioned RPC keeps the previous reservation contract available to existing
-- internal callers while ensuring new character-reference uploads bind the
-- local reference in the same database transaction as asset + outbox creation.
create or replace function public.pwa_reserve_character_reference_upload_v2(
  p_owner_id uuid,
  p_character_id uuid,
  p_local_reference_id uuid,
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
  v_result jsonb;
  v_updated integer;
begin
  if p_local_reference_id is null then
    raise exception 'local reference identifier is required' using errcode='22023';
  end if;

  -- The v1 reservation validates owner, character, file fingerprint, path,
  -- idempotency and outbox consistency. A later failure rolls back this
  -- nested function's writes together with the binding update.
  v_result := public.pwa_reserve_character_reference_upload(
    p_owner_id, p_character_id, p_asset_id, p_operation_id, p_event_id,
    p_idempotency_key, p_file_name, p_file_type, p_bucket, p_storage_path,
    p_size_bytes, p_content_sha256, p_width, p_height
  );

  update public.media_assets
  set local_reference_id = p_local_reference_id
  where id = p_asset_id
    and owner_id = p_owner_id
    and character_id = p_character_id
    and (local_reference_id is null or local_reference_id = p_local_reference_id);

  get diagnostics v_updated = row_count;
  if v_updated <> 1 then
    raise exception 'local reference binding conflicts with existing media association'
      using errcode='23505';
  end if;

  return v_result || jsonb_build_object('local_reference_id', p_local_reference_id);
end;
$$;

revoke all on function public.pwa_reserve_character_reference_upload_v2(
  uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,text,bigint,text,integer,integer
) from public, anon, authenticated;
grant execute on function public.pwa_reserve_character_reference_upload_v2(
  uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text,text,bigint,text,integer,integer
) to service_role;
