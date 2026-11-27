-- Transactional integration test for migration 0018 media upload + verifier RPCs.
-- RUN ONLY against a disposable Supabase project after 0005, 0012, 0017, 0018.
-- Required psql variables:
--   owner_id = existing auth.users UUID
--   character_id = existing public.characters UUID owned by owner_id
-- Example:
-- psql "$DISPOSABLE_DATABASE_URL" -v owner_id=... -v character_id=... \
--   -f 0018_media_upload_verification_transaction.sql
--
-- No Storage request is made. This exercises DB atomicity, idempotency, fencing,
-- terminal states, and grants. The separate worker tests mock Storage.

begin;

select set_config('pwa.test.owner_id', :'owner_id', true);
select set_config('pwa.test.character_id', :'character_id', true);

create or replace function public.pwa_test_fail_media_outbox_delivery_0018()
returns trigger
language plpgsql
as $$
begin
  if new.event_type='media_upload_verify_requested'
     and new.status='delivered' then
    raise exception 'Injected media outbox acknowledgement failure' using errcode='PZ018';
  end if;
  return new;
end;
$$;

drop trigger if exists pwa_test_fail_media_outbox_delivery_0018 on public.media_asset_outbox;
create trigger pwa_test_fail_media_outbox_delivery_0018
before update on public.media_asset_outbox
for each row execute function public.pwa_test_fail_media_outbox_delivery_0018();

do $$
declare
  v_owner uuid := current_setting('pwa.test.owner_id')::uuid;
  v_character uuid := current_setting('pwa.test.character_id')::uuid;
  v_asset uuid := gen_random_uuid();
  v_event uuid := gen_random_uuid();
  v_object uuid := gen_random_uuid();
  v_claim uuid := gen_random_uuid();
  v_stale_claim uuid := gen_random_uuid();
  v_digest text := 'b4b10f9c372171371977a874d1530fb2e6b6d0270f11b0b1b693b26e058c9a6d';
  v_path text;
  v_result jsonb;
  v_status text;
  v_outbox_status text;
  v_count bigint;
  v_asset2 uuid := gen_random_uuid();
  v_event2 uuid := gen_random_uuid();
  v_object2 uuid := gen_random_uuid();
  v_claim2 uuid := gen_random_uuid();
  v_attempt integer;
  v_retry_result jsonb;
begin
  if not exists (
    select 1 from public.characters where id=v_character and owner_id=v_owner
  ) then
    raise exception 'character_id must belong to owner_id';
  end if;
  if exists (
    select 1 from public.media_asset_outbox
    where event_type='media_upload_verify_requested'
      and status in ('pending','claimed')
  ) then
    raise exception 'Disposable test database must have no pending/claimed media verification events';
  end if;

  v_path := v_owner::text || '/characters/' || v_character::text || '/' || v_object::text || '.png';

  -- First reservation inserts the media row and outbox event atomically.
  v_result := public.pwa_reserve_character_reference_upload(
    v_owner,v_character,v_asset,v_event,v_event,
    'test-media-upload-' || v_event::text,
    'reference.png','image/png','studio-media',v_path,
    27,v_digest,3,3
  );
  if v_result->>'status' <> 'pending_upload' then
    raise exception 'New media reservation must be pending_upload';
  end if;

  -- Exact retry is idempotent: no duplicate asset or event.
  perform public.pwa_reserve_character_reference_upload(
    v_owner,v_character,v_asset,v_event,v_event,
    'test-media-upload-' || v_event::text,
    'reference.png','image/png','studio-media',v_path,
    27,v_digest,3,3
  );
  select count(*) into v_count from public.media_assets where id=v_asset and owner_id=v_owner;
  if v_count <> 1 then raise exception 'Idempotent reservation created duplicate media rows'; end if;
  select count(*) into v_count from public.media_asset_outbox
   where asset_id=v_asset and operation_id=v_event and event_type='media_upload_verify_requested';
  if v_count <> 1 then raise exception 'Idempotent reservation created duplicate outbox rows'; end if;

  -- Same owner/key with a different asset fingerprint must fail and roll back.
  begin
    perform public.pwa_reserve_character_reference_upload(
      v_owner,v_character,gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),
      'test-media-upload-' || v_event::text,
      'other.png','image/png','studio-media',v_path,
      27,v_digest,3,3
    );
    raise exception 'Expected idempotency-key collision was not raised';
  exception when sqlstate '23505' then
    null;
  end;

  -- Wrong owner cannot reserve against another user's character.
  begin
    perform public.pwa_reserve_character_reference_upload(
      gen_random_uuid(),v_character,gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),
      'test-foreign-owner-' || v_event::text,
      'foreign.png','image/png','studio-media',v_path,
      27,v_digest,3,3
    );
    raise exception 'Expected owner isolation failure was not raised';
  exception when sqlstate 'P0002' then
    null;
  end;

  -- Claim is fenced by a fresh token and returns only the reserved object identity.
  v_result := public.pwa_claim_media_upload_verification(v_claim,120);
  if v_result->>'asset_id' <> v_asset::text
     or v_result->>'claim_token' <> v_claim::text then
    raise exception 'Claim did not return the expected asset and fencing token';
  end if;

  -- Stale claim token cannot complete the media transition.
  begin
    perform public.pwa_complete_media_upload_verification(
      v_owner,v_asset,v_event,v_stale_claim,v_digest,27,'image/png',3,3
    );
    raise exception 'Expected stale claim rejection was not raised';
  exception when sqlstate 'P0002' then
    null;
  end;

  -- Wrong byte fingerprint must not mark the asset ready.
  begin
    perform public.pwa_complete_media_upload_verification(
      v_owner,v_asset,v_event,v_claim,
      '0000000000000000000000000000000000000000000000000000000000000000',
      27,'image/png',3,3
    );
    raise exception 'Expected media fingerprint mismatch was not raised';
  exception when sqlstate '23514' then
    null;
  end;

  select status into v_status from public.media_assets where id=v_asset;
  if v_status <> 'pending_upload' then
    raise exception 'Fingerprint mismatch changed media status unexpectedly: %',v_status;
  end if;

  -- Inject a failure at outbox acknowledgement. The asset UPDATE must roll back too.
  begin
    perform public.pwa_complete_media_upload_verification(
      v_owner,v_asset,v_event,v_claim,v_digest,27,'image/png',3,3
    );
    raise exception 'Expected outbox acknowledgement fault was not raised';
  exception when sqlstate 'PZ018' then
    null;
  end;
  select status into v_status from public.media_assets where id=v_asset;
  select status into v_outbox_status from public.media_asset_outbox where asset_id=v_asset;
  if v_status <> 'pending_upload' or v_outbox_status <> 'claimed' then
    raise exception 'Completion was not atomic: media %, outbox %',v_status,v_outbox_status;
  end if;

  -- Success after removing fault: media ready and event delivered atomically.
  drop trigger pwa_test_fail_media_outbox_delivery_0018 on public.media_asset_outbox;
  v_result := public.pwa_complete_media_upload_verification(
    v_owner,v_asset,v_event,v_claim,v_digest,27,'image/png',3,3
  );
  if v_result->>'status' <> 'ready' then
    raise exception 'Verified media did not transition to ready';
  end if;
  select status into v_outbox_status from public.media_asset_outbox where asset_id=v_asset;
  if v_outbox_status <> 'delivered' then
    raise exception 'Verification event was not delivered';
  end if;

  -- Upload request retry after worker completion must not downgrade ready.
  v_result := public.pwa_mark_character_reference_object_uploaded(v_owner,v_asset,v_event);
  if v_result->>'status' <> 'ready' then
    raise exception 'Late upload status update downgraded a ready asset';
  end if;

  -- Lease expiry reclaims the same event with a new fencing token.
  v_path := v_owner::text || '/characters/' || v_character::text || '/' || v_object2::text || '.png';
  perform public.pwa_reserve_character_reference_upload(
    v_owner,v_character,v_asset2,v_event2,v_event2,
    'test-media-retry-' || v_event2::text,
    'retry.png','image/png','studio-media',v_path,
    27,v_digest,3,3
  );
  v_stale_claim := gen_random_uuid();
  v_result := public.pwa_claim_media_upload_verification(v_stale_claim,120);
  if v_result->>'asset_id' <> v_asset2::text then
    raise exception 'Retry fixture was not claimed';
  end if;
  update public.media_asset_outbox
  set claim_expires_at=clock_timestamp() - interval '1 second'
  where id=v_event2 and claim_token=v_stale_claim;
  v_claim2 := gen_random_uuid();
  v_result := public.pwa_claim_media_upload_verification(v_claim2,120);
  if v_result->>'event_id' <> v_event2::text
     or v_result->>'claim_token' <> v_claim2::text then
    raise exception 'Expired claim was not recovered with a fresh token';
  end if;

  begin
    perform public.pwa_retry_media_upload_verification(
      v_owner,v_asset2,v_event2,v_stale_claim,1
    );
    raise exception 'Expired worker token unexpectedly scheduled a retry';
  exception when sqlstate 'P0002' then
    null;
  end;

  -- Exhaust the bounded retry budget. Move available_at forward in this test
  -- transaction rather than sleeping through the production backoff.
  for v_attempt in 2..8 loop
    v_retry_result := public.pwa_retry_media_upload_verification(
      v_owner,v_asset2,v_event2,v_claim2,1
    );
    if v_attempt < 8 then
      update public.media_asset_outbox
      set available_at=clock_timestamp()
      where id=v_event2 and status='pending';
      v_claim2 := gen_random_uuid();
      v_result := public.pwa_claim_media_upload_verification(v_claim2,120);
      if v_result->>'event_id' <> v_event2::text then
        raise exception 'Retry event was not reclaimed at attempt %',v_attempt+1;
      end if;
    end if;
  end loop;
  select status into v_status from public.media_assets where id=v_asset2;
  select status into v_outbox_status from public.media_asset_outbox where id=v_event2;
  if v_status <> 'upload_failed' or v_outbox_status <> 'dead_letter' then
    raise exception 'Retry exhaustion did not fail closed: media %, outbox %',v_status,v_outbox_status;
  end if;

  -- Server role only: browser roles cannot call the RPCs or inspect the outbox.
  if not has_function_privilege('service_role',
       'public.pwa_claim_media_upload_verification(uuid,integer)','EXECUTE')
     or not has_function_privilege('service_role',
       'public.pwa_complete_media_upload_verification(uuid,uuid,uuid,uuid,text,bigint,text,integer,integer)','EXECUTE')
     or not has_function_privilege('service_role',
       'public.pwa_retry_media_upload_verification(uuid,uuid,uuid,uuid,integer)','EXECUTE') then
    raise exception 'service_role is missing a media verification RPC grant';
  end if;
  if has_function_privilege('authenticated',
       'public.pwa_claim_media_upload_verification(uuid,integer)','EXECUTE')
     or has_function_privilege('anon',
       'public.pwa_claim_media_upload_verification(uuid,integer)','EXECUTE')
     or has_table_privilege('authenticated','public.media_asset_outbox','SELECT')
     or has_table_privilege('anon','public.media_asset_outbox','SELECT') then
    raise exception 'Browser roles unexpectedly have media worker privileges';
  end if;
  if not exists (
    select 1 from pg_proc p
    where p.oid='public.pwa_complete_media_upload_verification(uuid,uuid,uuid,uuid,text,bigint,text,integer,integer)'::regprocedure
      and p.prosecdef and p.proconfig @> array['search_path=pg_catalog, public']
  ) then
    raise exception 'Completion RPC is missing SECURITY DEFINER or fixed search_path';
  end if;
end;
$$;

rollback;
