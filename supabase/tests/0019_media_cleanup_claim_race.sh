#!/usr/bin/env bash
# Two independent psql sessions race to claim one character-media cleanup event.
# DISPOSABLE DATABASE ONLY. Requires psql and Python 3.
set -euo pipefail

: "${DISPOSABLE_DATABASE_URL:?Set DISPOSABLE_DATABASE_URL to a disposable Supabase/Postgres database}"
: "${PWA_TEST_OWNER_ID:?Set PWA_TEST_OWNER_ID to an existing disposable auth.users UUID}"

uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }
CHARACTER_ID="$(uuid)"
ASSET_ID="$(uuid)"
OBJECT_ID="$(uuid)"
OPERATION_ID="$(uuid)"
TOKEN_A="$(uuid)"
TOKEN_B="$(uuid)"
NEXT_TOKEN="$(uuid)"
PATH_KEY="${PWA_TEST_OWNER_ID}/characters/${CHARACTER_ID}/${OBJECT_ID}.png"
OUT_A="$(mktemp)"
OUT_B="$(mktemp)"

cleanup() { rm -f "$OUT_A" "$OUT_B"; }
trap cleanup EXIT

# This harness deliberately requires an isolated cleanup queue. It inserts a
# private media fixture, reserves cleanup, and removes the character only after
# the fresh fencing token completes the event. On failure, preserve fixtures
# for inspection in this disposable database.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" -v character_id="$CHARACTER_ID" \
  -v asset_id="$ASSET_ID" -v object_id="$OBJECT_ID" \
  -v operation_id="$OPERATION_ID" -v object_path="$PATH_KEY" <<'SQL'
do $$
begin
  if exists (
    select 1 from public.media_asset_outbox
    where event_type='media_cleanup_requested'
      and status in ('pending','claimed')
  ) then
    raise exception 'Disposable database must have no pending/claimed media cleanup events';
  end if;
end;
$$;
insert into public.characters(id,owner_id,name,reference_data)
values (:'character_id',:'owner_id','Disposable cleanup race fixture','{}'::jsonb);
insert into public.media_assets(
  id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
  metadata,version,operation_id,size_bytes,content_sha256,width,height
) values (
  :'asset_id',:'owner_id',:'character_id','race.png','image/png','studio-media','ready',
  :'object_path','{}'::jsonb,1,:'operation_id',128,repeat('a',64),8,8
);
select public.pwa_request_character_media_cleanup(
  :'owner_id',:'character_id',:'operation_id'
);
SQL

# Launch two independent database sessions before waiting for either.
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 -v token="$TOKEN_A" >"$OUT_A" <<'SQL' &
select public.pwa_claim_media_cleanup(:'token',120)::text;
SQL
PID_A=$!
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 -v token="$TOKEN_B" >"$OUT_B" <<'SQL' &
select public.pwa_claim_media_cleanup(:'token',120)::text;
SQL
PID_B=$!
wait "$PID_A"
wait "$PID_B"

python3 - "$OUT_A" "$OUT_B" "$TOKEN_A" "$TOKEN_B" "$ASSET_ID" <<'PY'
import json, pathlib, sys
paths, tokens, asset_id = sys.argv[1:3], set(sys.argv[3:5]), sys.argv[5]
results = []
for path in paths:
    raw = pathlib.Path(path).read_text().strip()
    # psql prints SQL NULL as an empty line with -qAt; that is the expected
    # losing worker result, not a missing execution result.
    if not raw:
        results.append(None)
        continue
    try:
        results.append(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FAIL: invalid claim JSON: {raw!r}") from exc
claims = [item for item in results if isinstance(item, dict)]
if len(claims) != 1 or results.count(None) != 1:
    raise SystemExit(f"FAIL: expected one claim and one SQL NULL: {results!r}")
claim = claims[0]
if claim.get("asset_id") != asset_id or claim.get("claim_token") not in tokens:
    raise SystemExit(f"FAIL: unexpected claimed fixture: {claim!r}")
print("PASS: exactly one of two concurrent cleanup workers claimed the event")
PY

EVENT_ID="$(psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v asset_id="$ASSET_ID" <<'SQL'
select id::text from public.media_asset_outbox
where asset_id=:'asset_id' and event_type='media_cleanup_requested';
SQL
)"
WINNER_TOKEN="$(psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v event_id="$EVENT_ID" <<'SQL'
select claim_token::text from public.media_asset_outbox where id=:'event_id';
SQL
)"

# Expire the first lease, then require a fresh token to reclaim it.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -v event_id="$EVENT_ID" <<'SQL'
update public.media_asset_outbox
set claim_expires_at=clock_timestamp()-interval '1 second'
where id=:'event_id' and status='claimed';
SQL
NEXT_RESULT="$(psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v token="$NEXT_TOKEN" <<'SQL'
select public.pwa_claim_media_cleanup(:'token',120)::text;
SQL
)"
python3 - "$NEXT_RESULT" "$NEXT_TOKEN" "$EVENT_ID" "$ASSET_ID" <<'PY'
import json, sys
result = json.loads(sys.argv[1])
if not isinstance(result, dict) or result.get("event_id") != sys.argv[3] \
   or result.get("asset_id") != sys.argv[4] or result.get("claim_token") != sys.argv[2] \
   or result.get("attempts") != 2:
    raise SystemExit(f"FAIL: expired event was not reclaimed with a fresh token: {result!r}")
print("PASS: expired cleanup lease was reclaimed with a fresh fencing token")
PY

# Stale worker A may neither retry nor complete after worker B has reclaimed.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" -v asset_id="$ASSET_ID" \
  -v event_id="$EVENT_ID" -v stale_token="$WINNER_TOKEN" <<'SQL'
select set_config('pwa.test.owner_id', :'owner_id', false);
select set_config('pwa.test.asset_id', :'asset_id', false);
select set_config('pwa.test.event_id', :'event_id', false);
select set_config('pwa.test.stale_token', :'stale_token', false);
do $$
declare v_rejected integer := 0;
begin
  begin
    perform public.pwa_retry_media_cleanup(
      current_setting('pwa.test.owner_id')::uuid,
      current_setting('pwa.test.asset_id')::uuid,
      current_setting('pwa.test.event_id')::uuid,
      current_setting('pwa.test.stale_token')::uuid,1
    );
  exception when sqlstate 'P0002' then v_rejected := v_rejected+1;
  end;
  begin
    perform public.pwa_complete_media_cleanup(
      current_setting('pwa.test.owner_id')::uuid,
      current_setting('pwa.test.asset_id')::uuid,
      current_setting('pwa.test.event_id')::uuid,
      current_setting('pwa.test.stale_token')::uuid
    );
  exception when sqlstate 'P0002' then v_rejected := v_rejected+1;
  end;
  if v_rejected <> 2 then
    raise exception 'Stale cleanup worker was not rejected by both fenced RPCs';
  end if;
end;
$$;
SQL

# Completion represents a confirmed Storage DELETE/404; this harness does not
# contact Storage. Finalize the character only after the media tombstone detaches.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" -v character_id="$CHARACTER_ID" \
  -v asset_id="$ASSET_ID" -v event_id="$EVENT_ID" -v token="$NEXT_TOKEN" <<'SQL'
select public.pwa_complete_media_cleanup(:'owner_id',:'asset_id',:'event_id',:'token');
select public.pwa_finalize_character_media_cleanup(:'owner_id',:'character_id');
SQL

echo "PASS: cleanup claim race, lease recovery, stale-token fencing, and finalization"
