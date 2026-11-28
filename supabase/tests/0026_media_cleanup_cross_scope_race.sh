#!/usr/bin/env bash
# Two-session races between whole-character cleanup and reference-replacement
# cleanup reservations. DISPOSABLE PostgreSQL ONLY; no Storage calls are made.
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

# Case A: replacement intent commits first. The real whole-character RPC
# races to enqueue its event and must lose the cross-scope unique-index fence.
CHAR_A="$(uuid)"; ASSET_A="$(uuid)"; OP_A="$(uuid)"; REPL_OP_A="$(uuid)"
EVENT_A="$(uuid)"; OBJECT_A="$(uuid)"
PATH_A="$PWA_TEST_OWNER_ID/characters/$CHAR_A/$OBJECT_A.png"

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_A" -v asset="$ASSET_A" \
  -v operation="$OP_A" -v path="$PATH_A" <<'SQL'
insert into public.characters(id,owner_id,name,reference_data)
values (:'character',:'owner','Cross-scope race replacement-first','{}'::jsonb);
insert into public.media_assets(
  id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
  metadata,version,operation_id,size_bytes,content_sha256,width,height
) values (
  :'asset',:'owner',:'character','race-a.png','image/png','studio-media','ready',
  :'path','{}'::jsonb,1,:'operation',128,repeat('a',64),8,8
);
SQL

PGAPPNAME=pwa_cross_scope_replacement_a psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v asset="$ASSET_A" -v operation="$REPL_OP_A" \
  -v event="$(uuid)" <<'SQL' >"$TMP/a.out" 2>&1 &
begin;
insert into public.media_asset_outbox(
  id,owner_id,asset_id,operation_id,event_type,idempotency_key,status
) values (
  :'event',:'owner',:'asset',:'operation',
  'media_reference_replacement_cleanup_requested',
  'cross-scope-race-a:' || :'asset','pending'
);
select 'REPLACEMENT_RESERVATION_HELD';
select pg_sleep(4);
commit;
SQL
A_PID=$!
wait_for_activity "pwa_cross_scope_replacement_a" sleeping

PGAPPNAME=pwa_cross_scope_character_a psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_A" -v operation="$OP_A" \
  -v asset="$ASSET_A" <<'SQL' >"$TMP/b.out" 2>&1 &
do $$
declare v_rejected boolean := false;
begin
  begin
    perform public.pwa_request_character_media_cleanup(
      :'owner',:'character',:'operation'
    );
  exception when unique_violation then
    v_rejected := true;
  end;
  if not v_rejected then
    raise exception 'whole-character cleanup bypassed active replacement reservation';
  end if;
  if (select cleanup_operation_id from public.characters where id=:'character') is not null
     or (select status from public.media_assets where id=:'asset') <> 'ready'
     or (select count(*) from public.media_asset_outbox
         where asset_id=:'asset' and status in ('pending','claimed')
           and event_type in ('media_cleanup_requested','media_reference_replacement_cleanup_requested')) <> 1 then
    raise exception 'replacement-first race left partial whole-character cleanup state';
  end if;
end;
$$;
SQL
B_PID=$!
wait_for_activity "pwa_cross_scope_character_a" lock_wait
wait "$A_PID"; A_PID=""
wait "$B_PID"; B_PID=""

echo "PASS: replacement-first concurrent reservation admits exactly one deletion intent"

# Case B: whole-character cleanup reserves first. A concurrent replacement
# event insert must wait for that transaction and then fail with unique_violation.
CHAR_B="$(uuid)"; ASSET_B="$(uuid)"; OP_B="$(uuid)"; REPL_OP_B="$(uuid)"
OBJECT_B="$(uuid)"; EVENT_B="$(uuid)"
PATH_B="$PWA_TEST_OWNER_ID/characters/$CHAR_B/$OBJECT_B.png"

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_B" -v asset="$ASSET_B" \
  -v operation="$OP_B" -v path="$PATH_B" <<'SQL'
insert into public.characters(id,owner_id,name,reference_data)
values (:'character',:'owner','Cross-scope race character-first','{}'::jsonb);
insert into public.media_assets(
  id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
  metadata,version,operation_id,size_bytes,content_sha256,width,height
) values (
  :'asset',:'owner',:'character','race-b.png','image/png','studio-media','ready',
  :'path','{}'::jsonb,1,:'operation',128,repeat('b',64),8,8
);
SQL

PGAPPNAME=pwa_cross_scope_character_b psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v character="$CHAR_B" -v operation="$OP_B" <<'SQL' >"$TMP/c.out" 2>&1 &
begin;
select public.pwa_request_character_media_cleanup(:'owner',:'character',:'operation');
select 'CHARACTER_CLEANUP_RESERVATION_HELD';
select pg_sleep(4);
commit;
SQL
A_PID=$!
wait_for_activity "pwa_cross_scope_character_b" sleeping

set +e
PGAPPNAME=pwa_cross_scope_replacement_b psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner="$PWA_TEST_OWNER_ID" -v asset="$ASSET_B" -v operation="$REPL_OP_B" \
  -v event="$EVENT_B" <<'SQL' >"$TMP/d.out" 2>&1 &
insert into public.media_asset_outbox(
  id,owner_id,asset_id,operation_id,event_type,idempotency_key,status
) values (
  :'event',:'owner',:'asset',:'operation',
  'media_reference_replacement_cleanup_requested',
  'cross-scope-race-b:' || :'asset','pending'
);
SQL
B_PID=$!
set -e
wait_for_activity "pwa_cross_scope_replacement_b" lock_wait
wait "$A_PID"; A_PID=""
set +e
wait "$B_PID"; B_STATUS=$?
set -e
B_PID=""

if [[ "$B_STATUS" -eq 0 ]] || ! grep -q 'media_asset_outbox_one_active_cleanup_per_asset' "$TMP/d.out"; then
  echo "FAIL: replacement reservation did not lose to active whole-character cleanup" >&2
  cat "$TMP/d.out" >&2
  exit 1
fi

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v asset="$ASSET_B" -v character="$CHAR_B" <<'SQL'
do $$
begin
  if (select count(*) from public.media_asset_outbox
      where asset_id=:'asset' and status in ('pending','claimed')
        and event_type in ('media_cleanup_requested','media_reference_replacement_cleanup_requested')) <> 1
     or (select status from public.media_assets where id=:'asset') <> 'cleanup_pending'
     or (select cleanup_operation_id from public.characters where id=:'character') is null then
    raise exception 'character-first race did not preserve exactly one whole-character deletion intent';
  end if;
end;
$$;
delete from public.media_asset_outbox where asset_id=:'asset';
delete from public.media_assets where id=:'asset';
delete from public.characters where id=:'character';
SQL

# Remove the first case's test-only replacement event and fixtures.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v asset="$ASSET_A" -v character="$CHAR_A" <<'SQL'
delete from public.media_asset_outbox where asset_id=:'asset';
delete from public.media_assets where id=:'asset';
delete from public.characters where id=:'character';
SQL

echo "PASS: both cross-scope reservation orderings serialize to one active deletion authorization"
