#!/usr/bin/env bash
# Restart test: one MQTT run with the worker stopped for a while in the middle (folder name ..._A_mqtt-<N>conn-restart_...,
# database tag stage label "arestart").
#   ORACLE=ubuntu@<oracle-ip> SSH_KEY=<key> ./loadtest/restart_test.sh <repeat> [rate=100] [stop_after_s=40] [down_s=20]
# Runs loadtest/measure_run.sh for the measured run. Meanwhile this script waits for the first readings to be stored,
# stops the worker stop_after_s later, starts it again down_s later, and saves next to the raw run:
#   worker_restart.txt (UTC times of each step), restart_summary.txt (sent vs stored, longest gap between stored_at values),
#   stored_per_second.csv (readings stored per second, all on the laptop clock).
# Run from the machine that hosts the Compose stack. Env: CONNECTIONS (MQTT connections, default 100).
set -u -o pipefail

repeat=${1:?usage: ORACLE=user@host SSH_KEY=<key> $0 <repeat> [rate] [stop_after_s] [down_s]}
rate=${2:-100} stop_after=${3:-40} down=${4:-20}
[ -n "${ORACLE:-}" ] && [ -n "${SSH_KEY:-}" ] || { echo "set ORACLE and SSH_KEY" >&2; exit 2; }

root=$(cd "$(dirname "$0")/.." && pwd)
export STAGE=arestart STAGE_NAME=A RUN_NOTE=restart CONNECTIONS=${CONNECTIONS:-100}
tag="arestartm${rate}r${repeat}"
compose="docker compose --env-file $root/.env -f $root/infra/docker-compose.yml"
db() { $compose exec -T postgres sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -At -F ,'; }
now() { date -u +%FT%T.%3NZ; }
times=$(mktemp)
trap '$compose start worker >/dev/null 2>&1; rm -f "$times"' EXIT   # never leave the worker stopped

(
    for _ in $(seq 1 600); do
        n=$(echo "SELECT count(*) FROM readings WHERE device_id LIKE '${tag}-%';" | db | tr -d '[:space:]')
        [ "${n:-0}" -gt 0 ] 2>/dev/null && break
        sleep 0.5
    done
    echo "first_rows_stored=$(now)" > "$times"
    sleep "$stop_after"
    echo "stop_requested=$(now)" >> "$times"
    $compose stop worker >/dev/null 2>&1
    echo "stop_returned=$(now)" >> "$times"
    sleep "$down"
    echo "start_requested=$(now)" >> "$times"
    $compose start worker >/dev/null 2>&1
    echo "start_returned=$(now)" >> "$times"
) &
bg=$!

"$root/loadtest/measure_run.sh" mqtt "$rate" "$repeat"; rc=$?
if [ $rc -ne 0 ]; then kill $bg 2>/dev/null; wait $bg 2>/dev/null; echo "measured run failed (exit $rc); worker restarted" >&2; exit $rc; fi
wait $bg

. "$root/loadtest/run_name.sh"
folder=$(ls -d "$root"/results/*_"$(run_suffix "$STAGE" mqtt "$rate" "$repeat")" | tail -1)
cp "$times" "$folder/worker_restart.txt"
started=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['started'])" "$folder/generator_summary.json")
stored=$(echo "SELECT count(*) FROM readings WHERE device_id LIKE '${tag}-%';" | db | tr -d '[:space:]')
{
    echo "run: $folder  (tag $tag)"
    cat "$folder/worker_restart.txt"
    echo "sent by the generator: $started   stored: $stored   missing (sent minus stored): $((started - stored))"
    echo "longest gap between consecutive stored_at values: seconds,previous_stored_at,next_stored_at (UTC)"
    echo "SELECT round(extract(epoch FROM gap)::numeric, 2),
        to_char(prev AT TIME ZONE 'UTC', 'HH24:MI:SS.MS'), to_char(stored_at AT TIME ZONE 'UTC', 'HH24:MI:SS.MS')
      FROM (SELECT stored_at, lag(stored_at) OVER (ORDER BY stored_at) AS prev,
                   stored_at - lag(stored_at) OVER (ORDER BY stored_at) AS gap
            FROM readings WHERE device_id LIKE '${tag}-%') t
      WHERE gap IS NOT NULL ORDER BY gap DESC LIMIT 1;" | db
} > "$folder/restart_summary.txt"
{
    echo "second_utc,stored"
    echo "SELECT to_char(date_trunc('second', stored_at) AT TIME ZONE 'UTC', 'HH24:MI:SS'), count(*)
      FROM readings WHERE device_id LIKE '${tag}-%' GROUP BY 1 ORDER BY 1;" | db
} > "$folder/stored_per_second.csv"
cat "$folder/restart_summary.txt"
