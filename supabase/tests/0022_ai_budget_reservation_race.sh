#!/usr/bin/env bash
set -euo pipefail

: "${DISPOSABLE_DATABASE_URL:?DISPOSABLE_DATABASE_URL is required}"
: "${PWA_TEST_OWNER_ID:?PWA_TEST_OWNER_ID is required}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

psql "$DISPOSABLE_DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -v owner_id="$PWA_TEST_OWNER_ID" <<'SQL'
insert into public.ai_budget_policies(scope_type,scope_key,period_start,period_end,limit_usd,enabled)
values ('platform','platform',date_trunc('month',now()),date_trunc('month',now()) + interval '1 month',0.10,true)
on conflict (scope_type,scope_key,period_start,period_end)
do update set limit_usd=excluded.limit_usd, enabled=true;
update public.ai_budget_control set enforcement_enabled=true,kill_switch_enabled=false where singleton=true;
SQL

export DISPOSABLE_DATABASE_URL PWA_TEST_OWNER_ID tmp_dir
pids=()
for i in $(seq 1 12); do
  (
    request_id="$(printf '%08x-0000-4000-8000-%012x' "$i" "$i")"
    idempotency_key="budget-race-key-$(printf '%04d' "$i")"
    fingerprint="$(printf 'request-%04d' "$i" | sha256sum | cut -d' ' -f1)"
    if psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
      -c "select reservation_id from public.reserve_ai_budget('$request_id','$PWA_TEST_OWNER_ID','$idempotency_key','$fingerprint','chat','deepseek','deepseek-flash',0.03)" \
      >"$tmp_dir/$i.out" 2>"$tmp_dir/$i.err"; then
      echo allowed >"$tmp_dir/$i.status"
    elif grep -q 'ai_budget_limit_exceeded' "$tmp_dir/$i.err"; then
      echo rejected >"$tmp_dir/$i.status"
    else
      cat "$tmp_dir/$i.err" >&2
      echo unexpected >"$tmp_dir/$i.status"
    fi
  ) &
  pids+=("$!")
done
# A rejected reservation is an expected non-zero psql result; collect each
# worker without allowing the shell's errexit mode to abort before assertions.
for pid in "${pids[@]}"; do
  wait "$pid" || true
done

allowed=0
rejected=0
unexpected=0
status_files=0
for status_file in "$tmp_dir"/*.status; do
  [[ -f "$status_file" ]] || continue
  status_files=$((status_files + 1))
  IFS= read -r state < "$status_file"
  case "$state" in
    allowed) allowed=$((allowed + 1)) ;;
    rejected) rejected=$((rejected + 1)) ;;
    *) unexpected=$((unexpected + 1)); echo "Unexpected reservation worker status: $state" >&2 ;;
  esac
done

echo "AI budget race results: files=$status_files allowed=$allowed rejected=$rejected unexpected=$unexpected"
if [[ "$status_files" != "12" || "$allowed" != "3" || "$rejected" != "9" || "$unexpected" != "0" ]]; then
  echo "AI budget concurrency invariant failed." >&2
  for error_file in "$tmp_dir"/*.err; do
    [[ -s "$error_file" ]] && cat "$error_file" >&2
  done
  exit 1
fi

echo "AI budget concurrency invariant passed: 12 concurrent reservations, exactly 3 accepted under USD 0.10 cap."
