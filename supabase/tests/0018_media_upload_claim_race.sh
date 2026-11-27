#!/usr/bin/env bash
# Two independent psql sessions race to claim exactly one media verification event.
# DISPOSABLE DATABASE ONLY. Requires psql, Python 3, and an isolated queue.
set -euo pipefail

: "${DISPOSABLE_DATABASE_URL:?Set DISPOSABLE_DATABASE_URL to a disposable Supabase/Postgres database}"
: "${PWA_TEST_OWNER_ID:?Set PWA_TEST_OWNER_ID to an existing auth.users UUID}"
: "${PWA_TEST_CHARACTER_ID:?Set PWA_TEST_CHARACTER_ID to a character owned by that user}"

uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }
ASSET_ID="$(uuid)"
EVENT_ID="$(uuid)"
OPERATION_ID="$(uuid)"
OBJECT_ID="$(uuid)"
TOKEN_A="$(uuid)"
TOKEN_B="$(uuid)"
IDEMPOTENCY_KEY="claim-race-${EVENT_ID}"
OBJECT_PATH="${PWA_TEST_OWNER_ID}/characters/${PWA_TEST_CHARACTER_ID}/${OBJECT_ID}.png"
OUT_A="$(mktemp)"
OUT_B="$(mktemp)"
CREATED=0

cleanup() {
  if [[ "$CREATED" == "1" ]]; then
    psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
      -v asset_id="$ASSET_ID" -v event_id="$EVENT_ID" <<'SQL' >/dev/null || true
delete from public.media_asset_outbox where id=:'event_id';
delete from public.media_assets where id=:'asset_id';
SQL
  fi
  rm -f "$OUT_A" "$OUT_B"
}
trap cleanup EXIT

# Never race against unrelated queue entries.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 <<'SQL'
do $$
begin
  if exists (
    select 1 from public.media_asset_outbox
    where event_type='media_upload_verify_requested'
      and status in ('pending','claimed')
  ) then
    raise exception 'Disposable database must have no pending/claimed media verification events';
  end if;
end;
$$;
SQL

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" -v character_id="$PWA_TEST_CHARACTER_ID" \
  -v asset_id="$ASSET_ID" -v event_id="$EVENT_ID" -v operation_id="$OPERATION_ID" \
  -v idempotency_key="$IDEMPOTENCY_KEY" -v object_path="$OBJECT_PATH" <<'SQL'
select public.pwa_reserve_character_reference_upload(
  :'owner_id', :'character_id', :'asset_id', :'operation_id', :'event_id',
  :'idempotency_key', 'claim-race.png', 'image/png', 'studio-media',
  :'object_path', 27,
  'b4b10f9c372171371977a874d1530fb2e6b6d0270f11b0b1b693b26e058c9a6d',
  3, 3
);
SQL
CREATED=1

# Separate database connections; launch both before waiting for either result.
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 -v token="$TOKEN_A" \
  -c "select public.pwa_claim_media_upload_verification(:'token',120)::text" >"$OUT_A" &
PID_A=$!
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 -v token="$TOKEN_B" \
  -c "select public.pwa_claim_media_upload_verification(:'token',120)::text" >"$OUT_B" &
PID_B=$!
wait "$PID_A"
wait "$PID_B"

python3 - "$OUT_A" "$OUT_B" "$TOKEN_A" "$TOKEN_B" "$EVENT_ID" <<'PY'
import json
import pathlib
import sys

a_path, b_path, token_a, token_b, event_id = sys.argv[1:]
results = []
for path in (a_path, b_path):
    raw = pathlib.Path(path).read_text().strip()
    if not raw:
        raise SystemExit("FAIL: a claim session returned no SQL result")
    try:
        results.append(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FAIL: invalid claim JSON: {raw!r}") from exc

claims = [item for item in results if isinstance(item, dict)]
if len(claims) != 1:
    raise SystemExit(f"FAIL: expected exactly one successful claim, received {len(claims)}: {results!r}")
claim = claims[0]
if claim.get("event_id") != event_id:
    raise SystemExit(f"FAIL: worker claimed an unexpected event: {claim!r}")
if claim.get("claim_token") not in {token_a, token_b}:
    raise SystemExit(f"FAIL: unexpected claim fencing token: {claim!r}")
if results.count(None) != 1:
    raise SystemExit(f"FAIL: losing worker should receive SQL NULL: {results!r}")
print("PASS: exactly one of two concurrent workers claimed the event")
print(f"Winning fencing token: {claim['claim_token']}")
PY

# Confirm one persisted claim and exactly one increment of attempts.
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 -v event_id="$EVENT_ID" <<'SQL'
do $$
declare
  v_count integer;
  v_attempts integer;
  v_status text;
begin
  select count(*), max(attempts), max(status)
    into v_count, v_attempts, v_status
  from public.media_asset_outbox
  where id=current_setting('pwa.test.event_id', true)::uuid;
  if v_count <> 1 or v_attempts <> 1 or v_status <> 'claimed' then
    raise exception 'Expected one persisted claim with attempts=1; got count %, attempts %, status %',
      v_count, v_attempts, v_status;
  end if;
end;
$$;
SQL

echo "PASS: persisted event has one active claim and attempts=1"
