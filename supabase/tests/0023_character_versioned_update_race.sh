#!/usr/bin/env bash
set -euo pipefail

: "${DISPOSABLE_DATABASE_URL:?DISPOSABLE_DATABASE_URL is required}"
: "${PWA_TEST_OWNER_ID:?PWA_TEST_OWNER_ID is required}"

local_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
character_id="$(psql "$DISPOSABLE_DATABASE_URL" -X -At -v ON_ERROR_STOP=1 -c \
  "select (public.pwa_create_character_idempotent('$PWA_TEST_OWNER_ID','$local_id','CAS race test',null,'{}'::jsonb)->>'id')")"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

for label in first second; do
  (
    psql "$DISPOSABLE_DATABASE_URL" -X -At -v ON_ERROR_STOP=1 -c \
      "select public.pwa_update_character_versioned('$PWA_TEST_OWNER_ID','$character_id',1,jsonb_build_object('name','$label'))"
  ) >"$tmp/$label.json" &
done
wait

python3 - "$tmp/first.json" "$tmp/second.json" <<'PY'
import json
import pathlib
import sys

results = [json.loads(pathlib.Path(path).read_text().strip()) for path in sys.argv[1:]]
successes = [item for item in results if item.get("version") == 2 and item.get("name") in {"first", "second"}]
conflicts = [item for item in results if item.get("conflict") is True and item.get("version") == 2]
if len(successes) != 1 or len(conflicts) != 1:
    raise SystemExit(f"expected exactly one CAS success and one stale conflict; got {results!r}")
print("PASS: concurrent character updates produce one version-2 success and one conflict")
PY

current="$(psql "$DISPOSABLE_DATABASE_URL" -X -At -v ON_ERROR_STOP=1 -c \
  "select version from public.characters where id='$character_id' and owner_id='$PWA_TEST_OWNER_ID'")"
if [[ "$current" != "2" ]]; then
  echo "Expected exactly one version increment; got version $current" >&2
  exit 1
fi
