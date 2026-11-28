#!/usr/bin/env bash
# Two-session races between upload verification completion and character cleanup.
# DISPOSABLE DATABASE ONLY. Never point this at production.
set -euo pipefail
: "${DISPOSABLE_DATABASE_URL:?Set DISPOSABLE_DATABASE_URL to disposable PostgreSQL}"
: "${PWA_TEST_OWNER_ID:?Set PWA_TEST_OWNER_ID to an existing disposable auth user UUID}"
uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }

wait_for_activity() {
  local app="$1" predicate="$2"
  for _ in $(seq 1 200); do
    if psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
      -v app="$app" -v predicate="$predicate" <<'SQL' | grep -qx 't'; then
select exists (
  select 1 from pg_stat_activity
  where application_name = :'app'
    and case :'predicate'
      when 'sleeping' then query ilike '%pg_sleep%'
      when 'lock_wait' then wait_event_type = 'Lock'
      else false
    end
);
SQL
      return 0
    fi
    sleep 0.05
  done
  echo "FAIL: timed out waiting for $app ($predicate)" >&2
  return 1
}

TMP="$(mktemp -d)"
A_PID="" B_PID=""
cleanup() {
  for pid in "$B_PID" "$A_PID"; do
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

# Case A: verifier takes the character KEY SHARE lock before its media row. Cleanup's
# FOR UPDATE must wait, then see ready after verification commits.
CHAR_A="$(uuid)"; ASSET_A="$(uuid)"; OP_A="$(uuid)"; EVENT_A="$(uuid)"
OBJECT_A="$(uuid)"; CLAIM_A="$(uuid)"
PATH_A="$PWA_TEST_OWNER_ID/characters/$CHAR_A/$OBJECT_A.png"
DIGEST_A="$(printf 'a%.0s' {1..64})"
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_A" -v asset="$ASSET_A" \
  -v operation="$OP_A" -v event="$EVENT_A" -v path="$PATH_A" \
  -v digest="$DIGEST_A" -v claim="$CLAIM_A" <<'SQL'
insert into public.characters(id,owner_id,name,reference_data)
values (:'character',:'owner','Upload-cleanup race A','{}'::jsonb);
select public.pwa_reserve_character_reference_upload(
  :'owner',:'character',:'asset',:'operation',:'event',
  'cross-worker-race-a-' || :'event',
  'race-a.png','image/png','studio-media',:'path',128,:'digest',8,8
);
select public.pwa_mark_character_reference_object_uploaded(:'owner',:'asset',:'operation');
select public.pwa_claim_media_upload_verification(:'claim',120);
SQL

PGAPPNAME=pwa_upload_verify_race_a psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_A" -v asset="$ASSET_A" -v event="$EVENT_A" \
  -v claim="$CLAIM_A" -v digest="$DIGEST_A" <<'SQL' >"$TMP/a.out" 2>&1 &
begin;
select id from public.characters where id=:'character' and owner_id=:'owner' for key share;
update public.media_assets set version=version where id=:'asset';
select pg_sleep(8);
select public.pwa_complete_media_upload_verification(
  :'owner',:'asset',:'event',:'claim',:'digest',128,'image/png',8,8
);
commit;
SQL
A_PID=$!
wait_for_activity "pwa_upload_verify_race_a" sleeping

PGAPPNAME=pwa_cleanup_race_a psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_A" -v operation="$OP_A" \
  >"$TMP/b.out" 2>&1 <<'SQL' &
select public.pwa_request_character_media_cleanup(:'owner',:'character',:'operation');
SQL
B_PID=$!
wait_for_activity "pwa_cleanup_race_a" lock_wait
wait "$A_PID"; A_PID=""
wait "$B_PID"; B_PID=""

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v asset="$ASSET_A" -v character="$CHAR_A" <<'SQL'
select 1 / (coalesce((select status='cleanup_pending' from public.media_assets where id=:'asset'),false)::int);
select 1 / ((select count(*)=1 from public.media_asset_outbox
  where asset_id=:'asset' and event_type='media_upload_verify_requested' and status='delivered')::int);
select 1 / ((select count(*)=1 from public.media_asset_outbox
  where asset_id=:'asset' and event_type='media_cleanup_requested' and status='pending')::int);
delete from public.media_assets where id=:'asset';
delete from public.characters where id=:'character';
SQL
echo "PASS: verifier follows character-to-media lock order; cleanup waits and sees ready media"

# Case B: upload reservation owns the character row first. Cleanup must wait,
# then reject the still-pending upload and roll back its deletion marker.
CHAR_B="$(uuid)"; ASSET_B="$(uuid)"; OP_B="$(uuid)"; EVENT_B="$(uuid)"
OBJECT_B="$(uuid)"
PATH_B="$PWA_TEST_OWNER_ID/characters/$CHAR_B/$OBJECT_B.png"
DIGEST_B="$(printf 'b%.0s' {1..64})"
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_B" <<'SQL'
SQL
PGAPPNAME=pwa_upload_reservation_race_b psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_B" -v asset="$ASSET_B" \
  -v operation="$OP_B" -v event="$EVENT_B" -v path="$PATH_B" -v digest="$DIGEST_B" \
  <<'SQL' >"$TMP/c.out" 2>&1 &
begin;
insert into public.characters(id,owner_id,name,reference_data)
values (:'character',:'owner','Upload-cleanup race B','{}'::jsonb);
select public.pwa_reserve_character_reference_upload(
  :'owner',:'character',:'asset',:'operation',:'event',
  'cross-worker-race-b-' || :'event',
  'race-b.png','image/png','studio-media',:'path',128,:'digest',8,8
);
select pg_sleep(8);
commit;
SQL
A_PID=$!
wait_for_activity "pwa_upload_reservation_race_b" sleeping

set +e
PGAPPNAME=pwa_cleanup_race_b psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_B" -v operation="$OP_B" \
  >"$TMP/d.out" 2>&1 <<'SQL' &
select public.pwa_request_character_media_cleanup(:'owner',:'character',:'operation');
SQL
B_PID=$!
set -e
wait_for_activity "pwa_cleanup_race_b" lock_wait
wait "$A_PID"; A_PID=""
set +e
wait "$B_PID"; B_STATUS=$?
set -e
B_PID=""
if [[ "$B_STATUS" -eq 0 ]] || ! grep -q 'upload in progress' "$TMP/d.out"; then
  echo "FAIL: cleanup did not reject the in-flight upload as expected" >&2
  cat "$TMP/d.out" >&2
  exit 1
fi

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v asset="$ASSET_B" -v character="$CHAR_B" <<'SQL'
select 1 / (coalesce((select status='pending_upload' from public.media_assets where id=:'asset'),false)::int);
select 1 / (coalesce((select cleanup_operation_id is null from public.characters where id=:'character'),false)::int);
select 1 / ((select count(*)=0 from public.media_asset_outbox
  where asset_id=:'asset' and event_type='media_cleanup_requested')::int);
delete from public.media_assets where id=:'asset';
delete from public.characters where id=:'character';
SQL
echo "PASS: upload reservation locks first; cleanup waits, rejects, and rolls back"
