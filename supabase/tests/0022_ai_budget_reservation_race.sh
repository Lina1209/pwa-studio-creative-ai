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

# Race identical idempotency keys: exactly one reservation must be created,
# while all callers receive the same existing reservation identity.
pids=()
for i in $(seq 1 12); do
  (
    psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At -F '|'  -c "select reservation_id,reservation_created from public.reserve_ai_budget('88888888-8888-4888-8888-888888888888','$PWA_TEST_OWNER_ID','budget-race-duplicate-0001','$(printf 'duplicate-race' | sha256sum | cut -d' ' -f1)','chat','deepseek','deepseek-flash',0.005)" >"$tmp_dir/duplicate-$i.out" 2>"$tmp_dir/duplicate-$i.err"
  ) &
  pids+=("$!")
done
duplicate_failures=0
for pid in "${pids[@]}"; do
  wait "$pid" || duplicate_failures=$((duplicate_failures + 1))
done

duplicate_rows=0
created_rows=0
duplicate_ids="$(cat "$tmp_dir"/duplicate-*.out 2>/dev/null | cut -d'|' -f1 | sort -u | wc -l | tr -d ' ')"
for output_file in "$tmp_dir"/duplicate-*.out; do
  [[ -f "$output_file" ]] || continue
  while IFS='|' read -r reservation_id created; do
    [[ -n "$reservation_id" ]] || continue
    duplicate_rows=$((duplicate_rows + 1))
    if [[ "$created" == "t" ]]; then created_rows=$((created_rows + 1)); fi
  done < "$output_file"
done

echo "AI budget idempotency race: rows=$duplicate_rows unique_ids=$duplicate_ids created=$created_rows failures=$duplicate_failures"
if [[ "$duplicate_rows" != "12" || "$duplicate_ids" != "1" || "$created_rows" != "1" || "$duplicate_failures" != "0" ]]; then
  echo "AI budget concurrent idempotency invariant failed." >&2
  for error_file in "$tmp_dir"/duplicate-*.err; do
    [[ -s "$error_file" ]] && cat "$error_file" >&2
  done
  exit 1
fi

echo "AI budget idempotency invariant passed: 12 identical concurrent calls created one reservation."

# Race identical settlement calls: every caller must observe success, but the
# reservation and append-only ledger must contain exactly one settlement event.
settlement_reservation_id="$(head -n 1 "$tmp_dir/duplicate-1.out" | cut -d'|' -f1)"
if [[ -z "$settlement_reservation_id" ]]; then
  echo "Could not resolve the shared idempotency reservation for settlement race." >&2
  exit 1
fi
pids=()
for i in $(seq 1 12); do
  (
    psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
      -c "select public.settle_ai_budget('$settlement_reservation_id',0.004)" \
      >"$tmp_dir/settle-$i.out" 2>"$tmp_dir/settle-$i.err"
  ) &
  pids+=("$!")
done
settlement_failures=0
for pid in "${pids[@]}"; do
  wait "$pid" || settlement_failures=$((settlement_failures + 1))
done
settlement_successes=0
for output_file in "$tmp_dir"/settle-*.out; do
  [[ -f "$output_file" ]] || continue
  if grep -qx 'settled' "$output_file"; then
    settlement_successes=$((settlement_successes + 1))
  fi
done
settlement_ledger_count="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select count(*) from public.ai_budget_ledger where reservation_id='$settlement_reservation_id' and event_type='settle'")"
settlement_actual="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select actual_usd from public.ai_budget_reservations where id='$settlement_reservation_id'")"
echo "AI budget settlement race: successes=$settlement_successes failures=$settlement_failures ledger_events=$settlement_ledger_count actual=$settlement_actual"
if [[ "$settlement_successes" != "12" || "$settlement_failures" != "0" || "$settlement_ledger_count" != "1" || "$settlement_actual" != "0.0040000000" ]]; then
  echo "AI budget concurrent settlement invariant failed." >&2
  for error_file in "$tmp_dir"/settle-*.err; do
    [[ -s "$error_file" ]] && cat "$error_file" >&2
  done
  exit 1
fi

echo "AI budget settlement invariant passed: 12 concurrent identical settlements produced one ledger event."

# Race an ambiguous-outcome marker against a confirmed settlement. The global
# transaction lock and row lock must serialize both operations: settlement
# wins or follows unknown, and the final reservation must be settled exactly
# once with the provider's actual amount.
race_request_id='99999999-9999-4999-8999-999999999999'
race_reservation_id="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select reservation_id from public.reserve_ai_budget('$race_request_id','$PWA_TEST_OWNER_ID','budget-unknown-settle-race-0001','$(printf 'unknown-settle-race' | sha256sum | cut -d' ' -f1)','chat','deepseek','deepseek-flash',0.005)")"
if [[ -z "$race_reservation_id" ]]; then
  echo "Could not create reservation for unknown/settlement race." >&2
  exit 1
fi
pids=()
for i in $(seq 1 6); do
  (
    psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
      -c "select public.mark_ai_budget_unknown('$race_reservation_id','concurrent_outcome_check')" \
      >"$tmp_dir/unknown-$i.out" 2>"$tmp_dir/unknown-$i.err"
  ) &
  pids+=("$!")
done
for i in $(seq 1 6); do
  (
    psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
      -c "select public.settle_ai_budget('$race_reservation_id',0.003)" \
      >"$tmp_dir/race-settle-$i.out" 2>"$tmp_dir/race-settle-$i.err"
  ) &
  pids+=("$!")
done
unknown_settle_failures=0
for pid in "${pids[@]}"; do
  wait "$pid" || unknown_settle_failures=$((unknown_settle_failures + 1))
done
race_settle_successes=0
for output_file in "$tmp_dir"/race-settle-*.out; do
  [[ -f "$output_file" ]] || continue
  if grep -qx 'settled' "$output_file"; then
    race_settle_successes=$((race_settle_successes + 1))
  fi
done
race_final_status="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select status from public.ai_budget_reservations where id='$race_reservation_id'")"
race_actual="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select actual_usd from public.ai_budget_reservations where id='$race_reservation_id'")"
race_settle_events="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select count(*) from public.ai_budget_ledger where reservation_id='$race_reservation_id' and event_type='settle'")"
race_unknown_events="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select count(*) from public.ai_budget_ledger where reservation_id='$race_reservation_id' and event_type='unknown'")"
echo "AI budget unknown/settlement race: final=$race_final_status settle_successes=$race_settle_successes failures=$unknown_settle_failures settle_events=$race_settle_events unknown_events=$race_unknown_events actual=$race_actual"
if [[ "$race_final_status" != "settled" || "$race_settle_successes" != "6" || "$unknown_settle_failures" != "0" || "$race_settle_events" != "1" || "$race_unknown_events" -gt "1" || "$race_actual" != "0.0030000000" ]]; then
  echo "AI budget unknown/settlement race invariant failed." >&2
  for error_file in "$tmp_dir"/unknown-*.err "$tmp_dir"/race-settle-*.err; do
    [[ -s "$error_file" ]] && cat "$error_file" >&2
  done
  exit 1
fi

echo "AI budget unknown/settlement race invariant passed: final state settled with one settlement event."

# Race mutually exclusive terminal outcomes: confirmed no-charge release and
# provider-cost settlement. Row/advisory locking must allow exactly one
# terminal ledger event; the losing operation must not overwrite that state.
terminal_request_id='aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa'
terminal_reservation_id="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select reservation_id from public.reserve_ai_budget('$terminal_request_id','$PWA_TEST_OWNER_ID','budget-release-settle-race-0001','$(printf 'release-settle-race' | sha256sum | cut -d' ' -f1)','chat','deepseek','deepseek-flash',0.005)")"
if [[ -z "$terminal_reservation_id" ]]; then
  echo "Could not create reservation for release/settlement race." >&2
  exit 1
fi
pids=()
for i in $(seq 1 8); do
  (
    psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
      -c "select public.release_ai_budget_no_charge('$terminal_reservation_id','confirmed_no_charge')" \
      >"$tmp_dir/release-$i.out" 2>"$tmp_dir/release-$i.err"
  ) &
  pids+=("$!")
done
for i in $(seq 1 8); do
  (
    psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
      -c "select public.settle_ai_budget('$terminal_reservation_id',0.002)" \
      >"$tmp_dir/terminal-settle-$i.out" 2>"$tmp_dir/terminal-settle-$i.err"
  ) &
  pids+=("$!")
done
terminal_worker_failures=0
for pid in "${pids[@]}"; do
  wait "$pid" || terminal_worker_failures=$((terminal_worker_failures + 1))
done
release_true=0
for output_file in "$tmp_dir"/release-*.out; do
  [[ -f "$output_file" ]] || continue
  if grep -qx 't' "$output_file"; then
    release_true=$((release_true + 1))
  fi
done
terminal_settle_successes=0
for output_file in "$tmp_dir"/terminal-settle-*.out; do
  [[ -f "$output_file" ]] || continue
  if grep -qx 'settled' "$output_file"; then
    terminal_settle_successes=$((terminal_settle_successes + 1))
  fi
done
terminal_status="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select status from public.ai_budget_reservations where id='$terminal_reservation_id'")"
terminal_event_count="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select count(*) from public.ai_budget_ledger where reservation_id='$terminal_reservation_id' and event_type in ('settle','release')")"
terminal_actual="$(psql "$DISPOSABLE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
  -c "select coalesce(actual_usd::text,'null') from public.ai_budget_reservations where id='$terminal_reservation_id'")"
echo "AI budget release/settlement race: final=$terminal_status release_confirmations=$release_true settlement_successes=$terminal_settle_successes worker_failures=$terminal_worker_failures terminal_events=$terminal_event_count actual=$terminal_actual"
if [[ "$terminal_event_count" != "1" ]]; then
  echo "AI budget release/settlement race invariant failed: expected one terminal ledger event." >&2
  for error_file in "$tmp_dir"/release-*.err "$tmp_dir"/terminal-settle-*.err; do
    [[ -s "$error_file" ]] && cat "$error_file" >&2
  done
  exit 1
fi
if [[ "$terminal_status" == "released" ]]; then
  if [[ "$terminal_worker_failures" != "8" || "$release_true" != "8" || "$terminal_settle_successes" != "0" || "$terminal_actual" != "null" ]]; then
    echo "Release-winning terminal outcome is inconsistent." >&2
    exit 1
  fi
elif [[ "$terminal_status" == "settled" ]]; then
  if [[ "$terminal_worker_failures" != "0" || "$release_true" != "0" || "$terminal_settle_successes" != "8" || "$terminal_actual" != "0.0020000000" ]]; then
    echo "Settlement-winning terminal outcome is inconsistent." >&2
    exit 1
  fi
else
  echo "Unexpected terminal reservation state: $terminal_status" >&2
  exit 1
fi

echo "AI budget release/settlement race invariant passed: exactly one terminal outcome was recorded."
