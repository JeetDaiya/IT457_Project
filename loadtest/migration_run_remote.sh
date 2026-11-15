#!/usr/bin/env bash
# B -> C migration test, one measured run, driven from the laptop (the cutover itself runs on the VM, see migration_cutover.sh).
#   ORACLE=ubuntu@<oracle-ip> ORACLE_KEY=<key> APP=ubuntu@<ec2-ip> APP_KEY=<key> \
#     ./loadtest/migration_run_remote.sh <http|mqtt> <repeat> [rate=100] [before_s=60]
# 1. migration_prepare.sh on the VM: reset minihs_src and minihs_migrated, seed ROWS (default 10000) readings per device x 100 devices
#    (SKIP_PREPARE=1 skips this),
# 2. starts the load through measure_run_remote.sh (MIGRATION=1, tag mig<h|m><rate>r<repeat>, DURATION default 420 s, so the load covers
#    before_s seconds of normal running, the stopped time and the time after; at most 100,000 messages),
# 3. before_s seconds after the first load rows are stored on minihs_src, runs migration_cutover.sh on the VM; after the load has
#    finished and the backlog is stored, runs migration_checks.sh (they would slow the worker if they ran during the load),
# 4. copies cutover_steps.txt and checks.txt next to the raw run and writes migration_summary.txt: where the stopped time went, the longest
#    gap between consecutive stored_at values of the load rows (the headline downtime), sent vs stored, seq gaps (seed and load devices),
#    stored_at NULL, server time before and after the cutover, and for MQTT the catch-up time after the restart.
# Never touches `minihs` on RDS or the Stage B database. Needs the same env as measure_run_remote.sh (CONNECTIONS for MQTT, default 100).
set -u -o pipefail

proto=${1:?usage: ORACLE=user@host ORACLE_KEY=<key> APP=user@host APP_KEY=<key> $0 <http|mqtt> <repeat> [rate] [before_s]}
repeat=${2:?repeat number missing}; rate=${3:-100} before=${4:-60}
for v in ORACLE ORACLE_KEY APP APP_KEY; do [ -n "${!v:-}" ] || { echo "set $v" >&2; exit 2; }; done
case $proto in http) letter=h ;; mqtt) letter=m ;; *) echo "protocol must be http or mqtt" >&2; exit 2 ;; esac

root=$(cd "$(dirname "$0")/.." && pwd)
. "$root/loadtest/run_name.sh"
export MIGRATION=1 STAGE=mig STAGE_NAME=BtoC CONNECTIONS=${CONNECTIONS:-100} DURATION=${DURATION:-420}
tag="mig${letter}${rate}r${repeat}"
rows=${ROWS:-10000}
local_root=${LOCAL_ROOT:-$root/results}
app_dir=${APP_DIR:-IT457_Project}
ssh_opts="-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3"
app_ssh() { ssh -n -i "$APP_KEY" $ssh_opts "$APP" "$@"; }
# SQL on stdin: src_db = the VM's minihs_src, dst_db = minihs_migrated on RDS (both through loadtest/migration_lib.sh on the VM)
src_db() { ssh -i "$APP_KEY" $ssh_opts "$APP" "cd $app_dir && . loadtest/migration_lib.sh && src_psql"; }
dst_db() { ssh -i "$APP_KEY" $ssh_opts "$APP" "cd $app_dir && . loadtest/migration_lib.sh && rds_psql"; }

if [ "${SKIP_PREPARE:-}" != 1 ]; then
    echo "preparing: reset both databases and seed 100 x $rows readings (a few minutes) ..." >&2
    app_ssh "cd $app_dir && ./loadtest/migration_prepare.sh $rows" >&2 || { echo "prepare failed" >&2; exit 1; }
fi

cut_log=$(mktemp); cut_rc=$(mktemp)
(
    for _ in $(seq 1 600); do
        n=$(echo "SELECT count(*) FROM readings WHERE device_id LIKE '${tag}-%';" | src_db | tr -d '[:space:]')
        [ "${n:-0}" -gt 0 ] 2>/dev/null && break
        sleep 1
    done
    sleep "$before"
    app_ssh "cd $app_dir && rm -rf /tmp/migration && ./loadtest/migration_cutover.sh" > "$cut_log" 2>&1
    echo $? > "$cut_rc"
) &
bg=$!

"$root/loadtest/measure_run_remote.sh" "$proto" "$rate" "$repeat"; rc=$?
if [ $rc -ne 0 ]; then kill $bg 2>/dev/null; wait $bg 2>/dev/null; echo "measured run failed (exit $rc)" >&2; exit $rc; fi
wait $bg
[ "$(cat "$cut_rc")" = 0 ] || { echo "the cutover failed (exit $(cat "$cut_rc")); this run is not valid:" >&2; cat "$cut_log" >&2; exit 1; }

# the data checks read every row on both databases, so they run only now, when the load has finished and the backlog is stored
echo "running the data checks (the load has finished) ..." >&2
app_ssh "cd $app_dir && ./loadtest/migration_checks.sh" > "$cut_log.checks" 2>&1; checks_rc=$?
folder=$(ls -d "$local_root"/*_"$(run_suffix "$STAGE" "$proto" "$rate" "$repeat")" | tail -1)
scp -q -i "$APP_KEY" $ssh_opts "$APP:/tmp/migration/cutover_steps.txt" "$APP:/tmp/migration/checks.txt" "$folder/" || { echo "cannot copy the cutover files" >&2; exit 1; }
cp "$cut_log" "$folder/cutover_output.txt"; rm -f "$cut_log" "$cut_log.checks" "$cut_rc"
steps="$folder/cutover_steps.txt"
stepval() { grep "^$1=" "$steps" | head -1 | cut -d= -f2; }
stop_at=$(stepval stop_requested); ok_at=$(stepval health_ok)
restart_hms=${ok_at#*T}; restart_hms=${restart_hms:0:8}

{
    echo "run: ${folder#"$root"/}  (tag $tag, database seeded with 100 x $rows rows)"
    echo "== where the stopped time went (VM clock) =="
    python3 "$root/loadtest/migration_summary.py" steps "$steps"
    echo "== sizes =="
    grep -E '^(source_rows|source_db_bytes|dump_bytes|max_id)=' "$steps"
    echo "== data checks, source vs RDS (rows with id <= max_id) =="
    cat "$folder/checks.txt"
    echo "== readings =="
    grep -E '^(sent by the generator|lost readings|stored rows)' "$folder/db_summary.txt"
    echo "rows with stored_at NULL (all rows): $(echo "SELECT count(*) FROM readings WHERE stored_at IS NULL;" | dst_db | tr -d '[:space:]')"
    echo "seed devices with a seq gap or a wrong range (want 0): $(echo "SELECT count(*) FROM (SELECT 1 FROM readings WHERE device_id LIKE 'seed-%' GROUP BY device_id HAVING min(seq) <> 1 OR max(seq) <> $rows OR count(DISTINCT seq) <> $rows) t;" | dst_db | tr -d '[:space:]')"
    echo "== headline downtime: longest gap between consecutive stored_at of the load rows =="
    echo "seconds,previous_stored_at,next_stored_at (UTC)"
    echo "SELECT round(extract(epoch FROM gap)::numeric, 2),
        to_char(prev AT TIME ZONE 'UTC', 'HH24:MI:SS.MS'), to_char(stored_at AT TIME ZONE 'UTC', 'HH24:MI:SS.MS')
      FROM (SELECT stored_at, lag(stored_at) OVER (ORDER BY stored_at) AS prev,
                   stored_at - lag(stored_at) OVER (ORDER BY stored_at) AS gap
            FROM readings WHERE device_id LIKE '${tag}-%') t
      WHERE gap IS NOT NULL ORDER BY gap DESC LIMIT 1;" | dst_db
    echo "== server time (stored_at - received_at, VM clock) before the stop (local Postgres) and after the restart (RDS) =="
    echo "part,rows,avg_ms,p95_ms"
    echo "SELECT 'before the stop', count(*), round((avg(extract(epoch FROM stored_at - received_at))*1000)::numeric, 2),
             round((percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM stored_at - received_at))*1000)::numeric, 2)
      FROM readings WHERE device_id LIKE '${tag}-%' AND received_at < '$stop_at'
      UNION ALL
      SELECT 'after the restart', count(*), round((avg(extract(epoch FROM stored_at - received_at))*1000)::numeric, 2),
             round((percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM stored_at - received_at))*1000)::numeric, 2)
      FROM readings WHERE device_id LIKE '${tag}-%' AND received_at >= '$ok_at';" | dst_db
} > "$folder/migration_summary.txt"

{
    echo "second_utc,stored"
    echo "SELECT to_char(date_trunc('second', stored_at) AT TIME ZONE 'UTC', 'HH24:MI:SS'), count(*)
      FROM readings WHERE device_id LIKE '${tag}-%' GROUP BY 1 ORDER BY 1;" | dst_db
} > "$folder/stored_per_second.csv"
if [ "$proto" = mqtt ]; then
    echo "== MQTT catch-up: seconds after the restart (from $restart_hms) until ten seconds in a row average the load rate (n/a if never) ==" >> "$folder/migration_summary.txt"
    python3 "$root/loadtest/migration_summary.py" catchup "$folder/stored_per_second.csv" "$restart_hms" "$rate" >> "$folder/migration_summary.txt"
fi
cat "$folder/migration_summary.txt"
[ "$checks_rc" = 0 ] || { echo "a data check FAILED (see checks.txt in the run folder)" >&2; exit 1; }
