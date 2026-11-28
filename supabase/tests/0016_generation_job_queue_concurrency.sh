#!/usr/bin/env bash
# Two independent PostgreSQL sessions race for one generation job and one outbox event.
# DISPOSABLE DATABASE ONLY. This does not start or enable a production worker.
set -euo pipefail
: "${DISPOSABLE_DATABASE_URL:?DISPOSABLE_DATABASE_URL is required}"
: "${PWA_TEST_OWNER_ID:?PWA_TEST_OWNER_ID is required}"
uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }
JOB_ID="$(uuid)"
OUTBOX_ID=""
TOKEN_A="$(uuid)"
TOKEN_B="$(uuid)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v job_id="$JOB_ID" -v owner_id="$PWA_TEST_OWNER_ID" <<'SQL'
insert into public.generation_jobs
  (id,owner_id,idempotency_key,request_fingerprint,job_type)
values
  (:'job_id',:'owner_id','concurrency-' || :'job_id',repeat('c',64),'image');
insert into public.generation_job_outbox(job_id,event_type)
values (:'job_id','job_queued');
SQL
OUTBOX_ID="$(psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v job_id="$JOB_ID" <<'SQL'
select id::text from public.generation_job_outbox
where job_id=:'job_id' and event_type='job_queued';
SQL
)"
[[ -n "$OUTBOX_ID" ]] || { echo "FAIL: outbox fixture missing" >&2; exit 1; }

# Both independent sessions start before either is awaited. The queue RPCs
# must serialize the single eligible row and issue only one live lease.
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v worker="concurrency-a" -v job_id="$JOB_ID" \
  >"$tmp_dir/job-a.out" 2>"$tmp_dir/job-a.err" <<'SQL' &
select to_jsonb(j)::text from public.claim_generation_job(:'worker',120) j
where j.id=:'job_id';
SQL
PID_A=$!
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v worker="concurrency-b" -v job_id="$JOB_ID" \
  >"$tmp_dir/job-b.out" 2>"$tmp_dir/job-b.err" <<'SQL' &
select to_jsonb(j)::text from public.claim_generation_job(:'worker',120) j
where j.id=:'job_id';
SQL
PID_B=$!
wait "$PID_A"
wait "$PID_B"

python3 - "$tmp_dir/job-a.out" "$tmp_dir/job-b.out" "$JOB_ID" <<'PY'
import json, pathlib, sys
paths, expected = sys.argv[1:3], sys.argv[3]
rows = []
for path in paths:
    raw = pathlib.Path(path).read_text().strip()
    rows.append(json.loads(raw) if raw else None)
claims = [row for row in rows if row is not None]
if len(claims) != 1 or sum(row is None for row in rows) != 1:
    raise SystemExit(f"FAIL: expected exactly one generation-job claimant, got {rows!r}")
claim = claims[0]
if claim.get("id") != expected or claim.get("status") != "processing" or not claim.get("lease_token"):
    raise SystemExit(f"FAIL: malformed generation job claim: {claim!r}")
print("PASS: exactly one of two concurrent sessions claimed the generation job")
PY

# Repeat the same two-session race for a single outbox event.
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v worker="dispatcher-a" -v outbox_id="$OUTBOX_ID" \
  >"$tmp_dir/outbox-a.out" 2>"$tmp_dir/outbox-a.err" <<'SQL' &
select to_jsonb(c)::text from public.claim_generation_outbox(:'worker',10,60) c
where c.outbox_id=:'outbox_id';
SQL
PID_A=$!
psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
  -v worker="dispatcher-b" -v outbox_id="$OUTBOX_ID" \
  >"$tmp_dir/outbox-b.out" 2>"$tmp_dir/outbox-b.err" <<'SQL' &
select to_jsonb(c)::text from public.claim_generation_outbox(:'worker',10,60) c
where c.outbox_id=:'outbox_id';
SQL
PID_B=$!
wait "$PID_A"
wait "$PID_B"

python3 - "$tmp_dir/outbox-a.out" "$tmp_dir/outbox-b.out" "$OUTBOX_ID" "$JOB_ID" <<'PY'
import json, pathlib, sys
paths = sys.argv[1:3]
expected_outbox, expected_job = sys.argv[3:5]
rows = []
for path in paths:
    raw = pathlib.Path(path).read_text().strip()
    rows.append(json.loads(raw) if raw else None)
claims = [row for row in rows if row is not None]
if len(claims) != 1 or sum(row is None for row in rows) != 1:
    raise SystemExit(f"FAIL: expected exactly one outbox claimant, got {rows!r}")
claim = claims[0]
if str(claim.get("outbox_id")) != expected_outbox or claim.get("job_id") != expected_job or not claim.get("claim_token"):
    raise SystemExit(f"FAIL: malformed outbox claim: {claim!r}")
print("PASS: exactly one of two concurrent sessions claimed the outbox event")
PY

echo "PASS: generation queue two-session claim races; no worker service was started"
