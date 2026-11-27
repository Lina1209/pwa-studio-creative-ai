#!/usr/bin/env bash
# Adversarial passport-reference write vs cleanup-intent serialization tests.
# DISPOSABLE DATABASE ONLY. Requires psql and Python 3.
set -euo pipefail

: "${DISPOSABLE_DATABASE_URL:?Set DISPOSABLE_DATABASE_URL to a disposable PostgreSQL database}"
: "${PWA_TEST_OWNER_ID:?Set PWA_TEST_OWNER_ID to an existing disposable auth.users UUID}"

uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }
TARGET_A="$(uuid)"
REF_A="$(uuid)"
ASSET_A="$(uuid)"
OBJECT_A="$(uuid)"
OP_A="$(uuid)"
TARGET_B="$(uuid)"
REF_B="$(uuid)"
ASSET_B="$(uuid)"
OBJECT_B="$(uuid)"
OP_B="$(uuid)"
PATH_A="${PWA_TEST_OWNER_ID}/characters/${TARGET_A}/${OBJECT_A}.png"
PATH_B="${PWA_TEST_OWNER_ID}/characters/${TARGET_B}/${OBJECT_B}.png"
OUT_A="$(mktemp)"
PID_A=""

cleanup() {
  if [[ -n "$PID_A" ]]; then
    kill "$PID_A" 2>/dev/null || true
    wait "$PID_A" 2>/dev/null || true
  fi
  rm -f "$OUT_A"
}
trap cleanup EXIT

# Case A: a reference writer acquires the exact-object advisory lock first.
# Cleanup must wait, observe the committed passport pointer, and roll back.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" -v target_id="$TARGET_A" -v ref_id="$REF_A" \
  -v asset_id="$ASSET_A" -v object_id="$OBJECT_A" -v operation_id="$OP_A" \
  -v object_path="$PATH_A" <<'SQL'
insert into public.characters(id,owner_id,name,reference_data)
values (:'target_id',:'owner_id','Reference race target A','{}'::jsonb),
       (:'ref_id',:'owner_id','Reference race pointer A','{}'::jsonb);
insert into public.media_assets(
  id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
  metadata,version,operation_id,size_bytes,content_sha256,width,height
) values (
  :'asset_id',:'owner_id',:'target_id','race-a.png','image/png','studio-media','ready',
  :'object_path','{}'::jsonb,1,:'operation_id',128,repeat('a',64),8,8
);
SQL

psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v ref_id="$REF_A" -v object_path="$PATH_A" >"$OUT_A" <<'SQL' &
begin;
update public.characters
set reference_data=jsonb_build_object('reference',:'object_path')
where id=:'ref_id';
select 'REFERENCE_LOCK_HELD';
select pg_sleep(2);
commit;
SQL
PID_A=$!

for _ in $(seq 1 40); do
  if grep -q 'REFERENCE_LOCK_HELD' "$OUT_A"; then break; fi
  sleep 0.05
done
if ! grep -q 'REFERENCE_LOCK_HELD' "$OUT_A"; then
  echo "FAIL: reference writer did not acquire its lock in time" >&2
  exit 1
fi

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" -v target_id="$TARGET_A" -v operation_id="$OP_A" <<'SQL'
select set_config('pwa.race.owner', :'owner_id', false);
select set_config('pwa.race.target', :'target_id', false);
select set_config('pwa.race.operation', :'operation_id', false);
do $$
declare v_rejected boolean := false;
begin
  begin
    perform public.pwa_request_character_media_cleanup(
      current_setting('pwa.race.owner')::uuid,
      current_setting('pwa.race.target')::uuid,
      current_setting('pwa.race.operation')::uuid
    );
  exception when sqlstate '23514' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'cleanup did not reject the committed external reference';
  end if;
end;
$$;
do $$
declare v_target uuid := current_setting('pwa.race.target')::uuid;
begin
  if (select cleanup_operation_id from public.characters where id=v_target) is not null
     or (select status from public.media_assets where id=:'asset_id') <> 'ready' then
    raise exception 'rejected cleanup left a deletion marker or changed the media state';
  end if;
end;
$$;
SQL
wait "$PID_A"
PID_A=""

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v target_id="$TARGET_A" -v ref_id="$REF_A" -v asset_id="$ASSET_A" <<'SQL'
update public.characters set reference_data='{}'::jsonb where id=:'ref_id';
delete from public.media_assets where id=:'asset_id';
delete from public.characters where id in (:'target_id',:'ref_id');
SQL
echo "PASS: reference writer wins; cleanup waits and refuses deletion"

# Case B: cleanup intent commits first. A later passport write to that object
# must acquire the same advisory lock and reject the pointer.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" -v target_id="$TARGET_B" -v ref_id="$REF_B" \
  -v asset_id="$ASSET_B" -v object_id="$OBJECT_B" -v operation_id="$OP_B" \
  -v object_path="$PATH_B" <<'SQL'
insert into public.characters(id,owner_id,name,reference_data)
values (:'target_id',:'owner_id','Reference race target B','{}'::jsonb),
       (:'ref_id',:'owner_id','Reference race pointer B','{}'::jsonb);
insert into public.media_assets(
  id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
  metadata,version,operation_id,size_bytes,content_sha256,width,height
) values (
  :'asset_id',:'owner_id',:'target_id','race-b.png','image/png','studio-media','ready',
  :'object_path','{}'::jsonb,1,:'operation_id',128,repeat('b',64),8,8
);
select public.pwa_request_character_media_cleanup(
  :'owner_id',:'target_id',:'operation_id'
);
select set_config('pwa.race.ref', :'ref_id', false);
select set_config('pwa.race.path', :'object_path', false);
do $$
declare v_rejected boolean := false;
begin
  begin
    update public.characters
    set reference_data=jsonb_build_object('reference',current_setting('pwa.race.path'))
    where id=current_setting('pwa.race.ref')::uuid;
  exception when sqlstate '23514' then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'passport pointer was accepted after cleanup intent';
  end if;
end;
$$;
do $$
begin
  if (select reference_data from public.characters where id=current_setting('pwa.race.ref')::uuid) <> '{}'::jsonb then
    raise exception 'rejected passport write changed the reference data';
  end if;
end;
$$;
delete from public.media_assets where id=:'asset_id';
delete from public.characters where id in (:'target_id',:'ref_id');
SQL
echo "PASS: cleanup wins; later reference writer is rejected"
