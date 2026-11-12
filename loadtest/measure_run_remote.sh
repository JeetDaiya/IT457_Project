#!/usr/bin/env bash
# One measured run when the stack runs on a remote VM (Stage B: the EC2 box), driven from any control machine
# (for example the laptop). measure_run.sh is the Stage A version: it assumes the stack runs on the machine you start it on.
#   ORACLE=ubuntu@<oracle-ip> ORACLE_KEY=<key> APP=ubuntu@<ec2-ip> APP_KEY=<key> \
#     ./loadtest/measure_run_remote.sh <http|mqtt> <rate> <repeat>
# 1. checks from the generator box that the API (and, for MQTT, the broker) answers and that the four containers run,
# 2. runs the generator on the Oracle box (container, see loadtest/README.md),
# 3. copies the raw run folder back (never overwrites), waits until the worker has finished storing,
# 4. reads the database numbers over SSH from the app host, saves them next to the run and appends one line to summary.csv.
# Env: STAGE (default b; the run tag), TARGET (host the generator calls, default the host part of APP), CONNECTIONS (MQTT
#      connections, default 1), STAGE_NAME / RUN_NOTE (folder name only, see run_name.sh), APP_DIR (repo on the app host,
#      default IT457_Project, relative to its home), REMOTE_ROOT (default results), LOCAL_ROOT (default <repo>/results),
#      COLLECT_ONLY=<run folder name> to skip the checks and the run and only collect that run.
# Server time (stored_at - received_at) uses the app host's clock only. The client round trip and the ping use the generator's clock.
set -u -o pipefail

if [ $# -ne 3 ] || [ -z "${ORACLE:-}" ] || [ -z "${ORACLE_KEY:-}" ] || [ -z "${APP:-}" ] || [ -z "${APP_KEY:-}" ]; then
    echo "usage: ORACLE=user@host ORACLE_KEY=<key> APP=user@host APP_KEY=<key> $0 <http|mqtt> <rate> <repeat>" >&2
    exit 2
fi
proto=$1 rate=$2 repeat=$3
case $proto in http) letter=h ;; mqtt) letter=m ;; *) echo "protocol must be http or mqtt" >&2; exit 2 ;; esac

root=$(cd "$(dirname "$0")/.." && pwd)
. "$root/loadtest/run_name.sh"
stage=${STAGE:-b}
target=${TARGET:-${APP#*@}}
app_dir=${APP_DIR:-IT457_Project}
remote_root=${REMOTE_ROOT:-results}
local_root=${LOCAL_ROOT:-$root/results}
tag="${stage}${letter}${rate}r${repeat}"
suffix=$(run_suffix "$stage" "$proto" "$rate" "$repeat")   # <stage>_<kind>_<rate>per-s_run<n>
ssh_opts="-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3"
oracle_ssh() { ssh -n -i "$ORACLE_KEY" $ssh_opts "$ORACLE" "$@"; }
app_ssh() { ssh -n -i "$APP_KEY" $ssh_opts "$APP" "$@"; }
box=it457-loadgen
compose="cd $app_dir && sudo docker compose --env-file .env -f infra/docker-compose.yml"
# SQL goes in on stdin: echo "SELECT 1;" | db
db() { ssh -i "$APP_KEY" $ssh_opts "$APP" "$compose exec -T postgres sh -c 'psql -U \$POSTGRES_USER -d \$POSTGRES_DB -At -F ,'"; }

if [ -z "${COLLECT_ONLY:-}" ]; then
    # ---- 1. checks, made from the generator box (the path the run will use) -----------------
    net=$(mktemp)
    {
        echo "checks from the generator box to $target:"
        health=$(oracle_ssh "curl -s -m 5 http://$target:8000/health" 2>&1)
        echo "GET /health: $health"
        echo "total time of 5 health requests (s, includes the TCP connect):"
        oracle_ssh "for i in 1 2 3 4 5; do curl -s -m 5 -o /dev/null -w '%{time_total} ' http://$target:8000/health; done; echo" 2>&1
        if [ "$proto" = mqtt ]; then
            if oracle_ssh "timeout 5 bash -c 'exec 3<>/dev/tcp/$target/1883'" 2>/dev/null; then echo "MQTT port 1883: open"
            else echo "MQTT port 1883: NOT reachable"; fi
        fi
        echo "containers running on the app host:"
        app_ssh "$compose ps --status running --format '{{.Service}}'" 2>&1 | sort | tr '\n' ' '; echo
        echo "app host memory (MiB) and load:"
        app_ssh "free -m | sed -n '1,2p'; uptime" 2>&1
    } > "$net" 2>&1
    fail=""
    grep -q '"status":"ok"' <<< "$(grep '^GET /health' "$net")" || fail="the API does not answer on $target:8000 (security group?)"
    if [ -z "$fail" ] && [ "$proto" = mqtt ] && grep -q "NOT reachable" "$net"; then fail="MQTT port 1883 on $target is not reachable from the generator box"; fi
    if [ -z "$fail" ]; then
        for svc in api mosquitto postgres worker; do
            grep -A1 '^containers running' "$net" | grep -qw "$svc" || fail="container $svc is not running on the app host"
        done
    fi
    if [ -n "$fail" ]; then echo "preflight FAILED: $fail" >&2; cat "$net" >&2; rm -f "$net"; exit 1; fi

    # ---- 2. run on the Oracle box -----------------------------------------------------------
    if [ "$proto" = http ]; then wrapper="./loadtest/run_http.sh $stage $rate $repeat http://$target:8000"
    else wrapper="./loadtest/run_mqtt.sh $stage $rate $repeat $target"; fi
    vm=$(mktemp); ssh -n -i "$APP_KEY" $ssh_opts "$APP" "vmstat -n 5" > "$vm" 2>&1 & vmpid=$!
    oracle_ssh "cd ~/$box && docker run --rm --network host --user \$(id -u):\$(id -g) \
        -e OUT_ROOT=/work/$remote_root -e CONNECTIONS=${CONNECTIONS:-1} -e STAGE_NAME=${STAGE_NAME:-} -e RUN_NOTE=${RUN_NOTE:-} -v \$PWD/loadtest:/work/loadtest:ro -v \$PWD/results:/work/results \
        -v \$PWD/calibration:/work/calibration it457-loadgen $wrapper > /dev/null 2>&1"
    gen_rc=$?
    kill $vmpid 2>/dev/null; wait $vmpid 2>/dev/null
    name=$(oracle_ssh "ls -1t ~/$box/$remote_root | grep '^[0-9-]*_${suffix}\$' | head -1")
    [ -n "$name" ] || { echo "generator produced no run folder (exit $gen_rc)" >&2; exit 1; }
else
    name=$COLLECT_ONLY; net=""; vm=""
fi

# ---- 3. copy the raw folder back, never overwrite ----------------------------------------------
dest="$local_root/$name"
if [ -e "$dest" ]; then echo "refusing to reuse $dest (raw results are never overwritten)" >&2; exit 1; fi
mkdir -p "$dest"
rsync -a -e "ssh -i $ORACLE_KEY $ssh_opts" "$ORACLE:$box/$remote_root/$name/" "$dest/" || { echo "copy failed" >&2; exit 1; }
if [ -n "$net" ]; then   # the machines' public addresses stay out of the repo (docs/DEPLOYMENT.md)
    content=$(<"$net")
    content=${content//${ORACLE#*@}/<oracle-ip>}; content=${content//$target/<app-ip>}
    printf '%s\n' "$content" > "$dest/network_check.txt"; rm -f "$net"
fi
[ -n "$vm" ] && mv "$vm" "$dest/app_vmstat.txt"

# ---- 4. wait until storing has finished (MQTT: the worker can lag behind the broker) ---------------
prev=-1; same=0
for _ in $(seq 1 60); do
    n=$(echo "SELECT count(*) FROM readings WHERE device_id LIKE '${tag}-%';" | db | tr -d '[:space:]')
    if [ "$n" = "$prev" ]; then same=$((same + 1)); else same=0; fi
    [ "$same" -ge 2 ] && break
    prev=$n; sleep 2
done

stats=$(echo "SELECT count(*), count(stored_at),
  coalesce(round((avg(extract(epoch FROM stored_at - received_at))*1000)::numeric, 2), 0),
  coalesce(round((percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM stored_at - received_at))*1000)::numeric, 2), 0)
  FROM readings WHERE device_id LIKE '${tag}-%';" | db | tr -d '[:space:]')
lost=$(echo "SELECT coalesce(sum(lost), 0) FROM (SELECT (max(seq) - min(seq) + 1) - count(DISTINCT seq) AS lost
  FROM readings WHERE device_id LIKE '${tag}-%' GROUP BY device_id) t;" | db | tr -d '[:space:]')
IFS=, read -r stored with_stored avg_ms p95_ms <<< "$stats"
# sent minus stored also sees readings lost at the end of a device's sequence, which the formula above cannot
sent=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['started'])" "$dest/generator_summary.json")
missing=$((sent - ${stored:-0}))
{
    echo "run: $name  (tag $tag)"
    echo "stored rows: $stored   rows with stored_at: $with_stored"
    echo "server time = stored_at - received_at (app host clock only): avg ${avg_ms} ms, slowest 5% (p95) ${p95_ms} ms"
    echo "lost readings = sum over devices of (max(seq)-min(seq)+1) - count(distinct seq): $lost"
    echo "sent by the generator: $sent   stored: $stored   missing (sent minus stored): $missing"
} > "$dest/db_summary.txt"

# client round trip and ping come from the generator's own files, reported separately
extra=$(python3 - "$dest" <<'EOF'
import csv, json, re, sys
d = sys.argv[1]
rtts = sorted(float(r["rtt_ms"]) for r in csv.DictReader(open(f"{d}/generator_log.csv")) if r["result"] == "ok" and r["rtt_ms"])
avg = sum(rtts) / len(rtts) if rtts else 0
p95 = rtts[max(0, int(len(rtts) * 0.95 + 0.9999) - 1)] if rtts else 0
s = json.load(open(f"{d}/generator_summary.json"))
m = re.search(r"= [\d.]+/([\d.]+)/", open(f"{d}/ping.txt").read())
print(f"client_rtt_avg_ms={avg:.1f} client_rtt_p95_ms={p95:.1f} ping_avg_ms={m.group(1) if m else 'n/a'} "
      f"ok={s['results']['ok']} achieved_rate={s['achieved_rate']}")
EOF
)
echo "client round trip / ping / generator: $extra" >> "$dest/db_summary.txt"

csv_file="$local_root/summary.csv"
[ -f "$csv_file" ] || echo "date,stage,protocol,rate,repeat,avg_delay_ms,p95_delay_ms,lost_readings,notes" > "$csv_file"
IFS=_ read -r _ csv_stage csv_kind _ <<< "$name"
echo "${name%%_*},$csv_stage,$csv_kind,$rate,$repeat,$avg_ms,$p95_ms,$lost,\"server time; $extra; stored=$stored missing=$missing\"" >> "$csv_file"
cat "$dest/db_summary.txt"
