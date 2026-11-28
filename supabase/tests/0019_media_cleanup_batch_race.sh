#!/usr/bin/env bash
# Stress one cleanup queue with 50 events and five independent worker sessions.
# DISPOSABLE DATABASE ONLY. Requires psql and Python 3.
set -euo pipefail

: "${DISPOSABLE_DATABASE_URL:?Set DISPOSABLE_DATABASE_URL to a disposable PostgreSQL database}"
: "${PWA_TEST_OWNER_ID:?Set PWA_TEST_OWNER_ID to an existing disposable auth.users UUID}"

OUT_DIR="$(mktemp -d)"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
  rm -rf "$OUT_DIR"
}
trap cleanup EXIT

# The test queue must be isolated so every returned claim belongs to this batch.
psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" <<'SQL'
do $$
begin
  if exists (
    select 1 from public.media_asset_outbox
    where event_type='media_cleanup_requested'
      and status in ('pending','claimed')
  ) then
    raise exception 'Disposable database must have an idle cleanup queue';
  end if;
end;
$$;

create table public.pwa_test_cleanup_batch_fixtures (
  owner_id uuid not null,
  character_id uuid primary key,
  asset_id uuid not null unique,
  operation_id uuid not null,
  object_path text not null
);

insert into public.pwa_test_cleanup_batch_fixtures(owner_id,character_id,asset_id,operation_id,object_path)
select :'owner_id',ids.character_id,ids.asset_id,ids.operation_id,
       :'owner_id' || '/characters/' || ids.character_id::text || '/' || ids.object_id::text || '.png'
from (
  select gen_random_uuid() character_id,gen_random_uuid() asset_id,
         gen_random_uuid() operation_id,gen_random_uuid() object_id
  from generate_series(1,50)
) ids;

insert into public.characters(id,owner_id,name,reference_data)
select character_id,owner_id,'Cleanup batch fixture','{}'::jsonb
from public.pwa_test_cleanup_batch_fixtures;

insert into public.media_assets(
  id,owner_id,character_id,file_name,file_type,bucket,status,storage_path,
  metadata,version,operation_id,size_bytes,content_sha256,width,height
)
select asset_id,owner_id,character_id,'batch.png','image/png','studio-media','ready',
       object_path,'{}'::jsonb,1,operation_id,128,repeat('a',64),8,8
from public.pwa_test_cleanup_batch_fixtures;

select set_config('pwa.batch.owner', :'owner_id', false);
do $$
declare f record;
begin
  for f in select * from public.pwa_test_cleanup_batch_fixtures order by character_id loop
    perform public.pwa_request_character_media_cleanup(
      f.owner_id,f.character_id,f.operation_id
    );
  end loop;
end;
$$;
SQL

# Five independent sessions each make ten claims with fresh tokens.
for worker in 1 2 3 4 5; do
  psql "$DISPOSABLE_DATABASE_URL" -X -qAt -v ON_ERROR_STOP=1 \
    >"$OUT_DIR/worker-$worker.jsonl" <<'SQL' &
select public.pwa_claim_media_cleanup(gen_random_uuid(),120)::text
from generate_series(1,10);
SQL
  PIDS+=("$!")
done
for pid in "${PIDS[@]}"; do wait "$pid"; done
PIDS=()

# Validate every event was claimed once, with unique fencing tokens. Emit only
# UUID-validated completion statements for the same claims.
python3 - "$OUT_DIR" <<'PY' | psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1
import json, pathlib, sys, uuid
directory = pathlib.Path(sys.argv[1])
claims = []
for path in sorted(directory.glob("worker-*.jsonl")):
    for raw in path.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        item = json.loads(raw)
        if not isinstance(item, dict):
            raise SystemExit(f"FAIL: non-object claim from {path}: {item!r}")
        for key in ("owner_id", "character_id", "asset_id", "event_id", "claim_token"):
            item[key] = str(uuid.UUID(item[key]))
        if item.get("bucket") != "studio-media":
            raise SystemExit(f"FAIL: unexpected bucket in claim: {item!r}")
        claims.append(item)
if len(claims) != 50:
    raise SystemExit(f"FAIL: expected 50 claims, received {len(claims)}")
for key in ("event_id", "asset_id", "claim_token"):
    values = [item[key] for item in claims]
    if len(set(values)) != 50:
        raise SystemExit(f"FAIL: duplicate {key} across workers")
for item in claims:
    print(
        "select public.pwa_complete_media_cleanup("
        f"'{item['owner_id']}'::uuid,'{item['asset_id']}'::uuid,"
        f"'{item['event_id']}'::uuid,'{item['claim_token']}'::uuid);"
    )
    print(
        "select public.pwa_finalize_character_media_cleanup("
        f"'{item['owner_id']}'::uuid,'{item['character_id']}'::uuid);"
    )
print("DO $$ BEGIN", file=sys.stderr)
print("RAISE NOTICE 'PASS: 50 unique events claimed by five independent sessions';", file=sys.stderr)
print("END $$;", file=sys.stderr)
PY

psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 <<'SQL'
do $$
begin
  if exists (
    select 1 from public.pwa_test_cleanup_batch_fixtures f
    join public.characters c on c.id=f.character_id
  ) then
    raise exception 'batch finalization left character rows behind';
  end if;
  if exists (
    select 1 from public.pwa_test_cleanup_batch_fixtures f
    join public.media_assets a on a.id=f.asset_id
    where a.status <> 'deleted' or a.character_id is not null
  ) then
    raise exception 'batch completion left attached or non-deleted media rows';
  end if;
  if exists (
    select 1 from public.pwa_test_cleanup_batch_fixtures f
    join public.media_asset_outbox e on e.asset_id=f.asset_id
    where e.status <> 'delivered'
  ) then
    raise exception 'batch completion left undelivered cleanup events';
  end if;
end;
$$;
drop table public.pwa_test_cleanup_batch_fixtures;
SQL

echo "PASS: 50 cleanup events processed by five concurrent workers"
