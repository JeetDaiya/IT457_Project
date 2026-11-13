#!/usr/bin/env bash
# Restart test when the stack runs on a remote VM (Stage B): one MQTT run with the worker stopped for a while in the middle.
# restart_test.sh is the Stage A version (it needs the stack on the machine you start it on). Folder name ..._B_mqtt-<N>conn-restart_...,
# database tag stage label "brestart".
#   ORACLE=ubuntu@<oracle-ip> ORACLE_KEY=<key> APP=ubuntu@<ec2-ip> APP_KEY=<key> \
#     ./loadtest/restart_test_remote.sh <repeat> [rate=100] [stop_after_s=40] [down_s=20]
# Runs loadtest/measure_run_remote.sh for the measured run. Meanwhile this script waits for the first readings to be stored,
# stops the worker on the VM stop_after_s later, starts it again down_s later, and saves next to the raw run:
#   worker_restart.txt (UTC times of each step), restart_summary.txt (sent vs stored, longest gap between stored_at values),
#   stored_per_second.csv (readings stored per second). Every timestamp is taken on the VM's own clock, the same clock as stored_at.
# Env: as for measure_run_remote.sh (APP_DIR, LOCAL_ROOT, ...); CONNECTIONS (MQTT connections, default 100).
set -u -o pipefail

repeat=${1:?usage: ORACLE=user@host ORACLE_KEY=<key> APP=user@host APP_KEY=<key> $0 <repeat> [rate] [stop_after_s] [down_s]}
rate=${2:-100} stop_after=${3:-40} down=${4:-20}
if [ -z "${ORACLE:-}" ] || [ -z "${ORACLE_KEY:-}" ] || [ -z "${APP:-}" ] || [ -z "${APP_KEY:-}" ]; then
    echo "set ORACLE, ORACLE_KEY, APP and APP_KEY" >&2; exit 2
fi

root=$(cd "$(dirname "$0")/.." && pwd)
. "$root/loadtest/run_name.sh"
export STAGE=brestart STAGE_NAME=B RUN_NOTE=restart CONNECTIONS=${CONNECTIONS:-100}
tag="brestartm${rate}r${repeat}"
local_root=${LOCAL_ROOT:-$root/results}
app_dir=${APP_DIR:-IT457_Project}
ssh_opts="-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3"
compose="cd $app_dir && sudo docker compose --env-file .env -f infra/docker-compose.yml"
app_ssh() { ssh -n -i "$APP_KEY" $ssh_opts "$APP" "$@"; }
# SQL goes in on stdin: echo "SELECT 1;" | db
db() { ssh -i "$APP_KEY" $ssh_opts "$APP" "$compose exec -T postgres sh -c 'psql -U \$POSTGRES_USER -d \$POSTGRES_DB -At -F ,'"; }
vm_now() { app_ssh "date -u +%FT%T.%3NZ"; }
worker_step() {  # <stop|start>: both timestamps come from the VM, so they can be compared with stored_at
    app_ssh "echo ${1}_requested=\$(date -u +%FT%T.%3NZ); $compose $1 worker >/dev/null 2>&1; echo ${1}_returned=\$(date -u +%FT%T.%3NZ)"
}
times=$(mktemp)
trap 'app_ssh "$compose start worker" >/dev/null 2>&1; rm -f "$times"' EXIT   # never leave the worker stopped

(
    for _ in $(seq 1 600); do
        n=$(echo "SELECT count(*) FROM readings WHERE device_id LIKE '${tag}-%';" | db | tr -d '[:space:]')
        [ "${n:-0}" -gt 0 ] 2>/dev/null && break
        sleep 1
    done
    echo "first_rows_stored=$(vm_now)" > "$times"
    sleep "$stop_after"
    worker_step stop >> "$times"
    sleep "$down"
    worker_step start >> "$times"
) &
bg=$!

"$root/loadtest/measure_run_remote.sh" mqtt "$rate" "$repeat"; rc=$?
if [ $rc -ne 0 ]; then kill $bg 2>/dev/null; wait $bg 2>/dev/null; echo "measured run failed (exit $rc); worker restarted" >&2; exit $rc; fi
wait $bg

folder=$(ls -d "$local_root"/*_"$(run_suffix "$STAGE" mqtt "$rate" "$repeat")" | tail -1)
cp "$times" "$folder/worker_restart.txt"
started=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['started'])" "$folder/generator_summary.json")
stored=$(echo "SELECT count(*) FROM readings WHERE device_id LIKE '${tag}-%';" | db | tr -d '[:space:]')
{
    echo "run: ${folder#"$root"/}  (tag $tag)"
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
