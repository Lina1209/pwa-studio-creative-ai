#!/usr/bin/env bash
# Two independent psql sessions race to claim one media verification event,
# then the winning lease expires and a second worker reclaims it.
# DISPOSABLE DATABASE ONLY. Requires psql and Python 3.
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

# Require an isolated queue so the two sessions can only race for our fixture.
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

# Launch both independent database sessions before waiting for either.
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 -v token="$TOKEN_A" >"$OUT_A" <<'SQL' &
select public.pwa_claim_media_upload_verification(:'token',120)::text;
SQL
PID_A=$!
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 -v token="$TOKEN_B" >"$OUT_B" <<'SQL' &
select public.pwa_claim_media_upload_verification(:'token',120)::text;
SQL
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
PY

WINNER_TOKEN="$(psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v event_id="$EVENT_ID" <<'SQL'
select claim_token::text from public.media_asset_outbox where id=:'event_id';
SQL
)"
NEXT_TOKEN="$(uuid)"

# Force expiry deterministically, without sleeping or changing the system clock.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -v event_id="$EVENT_ID" <<'SQL'
update public.media_asset_outbox
set claim_expires_at=clock_timestamp() - interval '1 second'
where id=:'event_id' and status='claimed';
SQL

NEXT_RESULT="$(psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 -v token="$NEXT_TOKEN" <<'SQL'
select public.pwa_claim_media_upload_verification(:'token',120)::text;
SQL
)"
python3 - "$NEXT_RESULT" "$NEXT_TOKEN" "$EVENT_ID" <<'PY'
import json, sys
result = json.loads(sys.argv[1])
if not isinstance(result, dict) or result.get("event_id") != sys.argv[3] or result.get("claim_token") != sys.argv[2]:
    raise SystemExit(f"FAIL: expired event was not reclaimed with a fresh token: {result!r}")
print("PASS: expired lease was reclaimed with a new fencing token")
PY

# The previous worker's token must be unable to complete OR schedule a retry.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" -v asset_id="$ASSET_ID" \
  -v event_id="$EVENT_ID" -v stale_token="$WINNER_TOKEN" <<'SQL'
select set_config('pwa.test.owner_id', :'owner_id', false);
select set_config('pwa.test.asset_id', :'asset_id', false);
select set_config('pwa.test.event_id', :'event_id', false);
select set_config('pwa.test.stale_token', :'stale_token', false);
do $$
declare
  v_rejected integer := 0;
begin
  begin
    perform public.pwa_retry_media_upload_verification(
      current_setting('pwa.test.owner_id')::uuid,
      current_setting('pwa.test.asset_id')::uuid,
      current_setting('pwa.test.event_id')::uuid,
      current_setting('pwa.test.stale_token')::uuid,1
    );
  exception when sqlstate 'P0002' then
    v_rejected := v_rejected + 1;
  end;
  begin
    perform public.pwa_complete_media_upload_verification(
      current_setting('pwa.test.owner_id')::uuid,
      current_setting('pwa.test.asset_id')::uuid,
      current_setting('pwa.test.event_id')::uuid,
      current_setting('pwa.test.stale_token')::uuid,
      'b4b10f9c372171371977a874d1530fb2e6b6d0270f11b0b1b693b26e058c9a6d',
      27,'image/png',3,3
    );
  exception when sqlstate 'P0002' then
    v_rejected := v_rejected + 1;
  end;
  if v_rejected <> 2 then
    raise exception 'Stale worker token was not rejected by both fenced RPCs';
  end if;
end;
$$;
SQL

# Confirm the fresh worker still owns the sole active claim and attempts=2.
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v event_id="$EVENT_ID" -v next_token="$NEXT_TOKEN" <<'SQL'
select set_config('pwa.test.event_id', :'event_id', false);
select set_config('pwa.test.next_token', :'next_token', false);
do $$
declare
  v_count integer;
  v_attempts integer;
  v_status text;
  v_token uuid;
begin
  select count(*), max(attempts), max(status)
    into v_count, v_attempts, v_status
  from public.media_asset_outbox
  where id=current_setting('pwa.test.event_id')::uuid;
  select claim_token into v_token
  from public.media_asset_outbox
  where id=current_setting('pwa.test.event_id')::uuid;
  if v_count <> 1 or v_attempts <> 2 or v_status <> 'claimed'
     or v_token <> current_setting('pwa.test.next_token')::uuid then
    raise exception 'Unexpected final claim state: count %, attempts %, status %, token %',
      v_count, v_attempts, v_status, v_token;
  end if;
end;
$$;
SQL

echo "PASS: two-worker claim race, lease recovery, and stale-token fencing"
