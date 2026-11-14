#!/usr/bin/env bash
# One measured run when the stack runs on a remote VM (Stage B: the EC2 box), driven from any control machine
# (for example the laptop). measure_run.sh is the Stage A version: it assumes the stack runs on the machine you start it on.
#   ORACLE=ubuntu@<oracle-ip> ORACLE_KEY=<key> APP=ubuntu@<ec2-ip> APP_KEY=<key> \
#     ./loadtest/measure_run_remote.sh <http|mqtt> <rate> <repeat>
# 1. checks from the generator box that the API (and, for MQTT, the broker) answers and that the four containers run,
# 2. runs the generator on the Oracle box (container, see loadtest/README.md),
# 3. copies the raw run folder back (never overwrites), waits until the worker has finished storing,
# 4. reads the database numbers over SSH from the app host, saves them next to the run and appends one line to summary.csv.
# Env: STAGE (default b; the run tag), DURATION (seconds, default 120; passed to the generator), TARGET (host the generator calls, default the host part of APP), CONNECTIONS (MQTT
#      connections, default 1), STAGE_NAME / RUN_NOTE (folder name only, see run_name.sh), APP_DIR (repo on the app host,
#      default IT457_Project, relative to its home), REMOTE_ROOT (default results), LOCAL_ROOT (default <repo>/results),
#      COLLECT_ONLY=<run folder name> to skip the checks and the run and only collect that run.
# Server time (stored_at - received_at) uses the app host's clock only. The client round trip and the ping use the generator's clock.
#
# Stage C (IoT Core -> SQS -> worker -> RDS): the same script with STAGE_C=1, MQTT only. Needs IOT_ENDPOINT (device data endpoint),
#   IOT_CERT_DIR (absolute path on the Oracle box) with the file names IOT_CA, IOT_CERT and IOT_KEY in it. Defaults: STAGE c,
#   STAGE_NAME C, CONNECTIONS 100. It checks the API and port 8883, requires an empty queue and no it-% rows (PURGE=1 empties the queue
#   first; needs sqs:PurgeQueue), samples the queue every 5 s into queue_depth.csv, waits up to DRAIN_MAX_S (default 900) for it to
#   drain, and adds "rows with stored_at NULL" and "queue drained after N s" to db_summary.txt. The IoT endpoint and the addresses
#   are replaced by <iot-endpoint>, <app-ip> and <oracle-ip> in the copies of settings.json, ping.txt and network_check.txt.
set -u -o pipefail

if [ $# -ne 3 ] || [ -z "${ORACLE:-}" ] || [ -z "${ORACLE_KEY:-}" ] || [ -z "${APP:-}" ] || [ -z "${APP_KEY:-}" ]; then
    echo "usage: ORACLE=user@host ORACLE_KEY=<key> APP=user@host APP_KEY=<key> $0 <http|mqtt> <rate> <repeat>" >&2
    exit 2
fi
proto=$1 rate=$2 repeat=$3
case $proto in http) letter=h ;; mqtt) letter=m ;; *) echo "protocol must be http or mqtt" >&2; exit 2 ;; esac

root=$(cd "$(dirname "$0")/.." && pwd)
. "$root/loadtest/run_name.sh"
c_mode=${STAGE_C:-}
if [ "$c_mode" = 1 ]; then
    [ "$proto" = mqtt ] || { echo "STAGE_C=1 is MQTT only (IoT Core)" >&2; exit 2; }
    for v in IOT_ENDPOINT IOT_CERT_DIR IOT_CA IOT_CERT IOT_KEY; do
        [ -n "${!v:-}" ] || { echo "STAGE_C=1 needs $v" >&2; exit 2; }
    done
    STAGE_NAME=${STAGE_NAME:-C}; CONNECTIONS=${CONNECTIONS:-100}
    stage=${STAGE:-c}; compose_file=infra/docker-compose.stage-c.yml
else
    stage=${STAGE:-b}; compose_file=infra/docker-compose.yml
fi
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
compose="cd $app_dir && sudo docker compose --env-file .env -f $compose_file"
# SQL goes in on stdin: echo "SELECT 1;" | db
if [ "$c_mode" = 1 ]; then   # RDS is private: psql runs in a throwaway container on the app host (password and CA bundle stay there)
    db() { ssh -i "$APP_KEY" $ssh_opts "$APP" "cd $app_dir && set -a && . ./.env && set +a && sudo docker run --rm -i -e PGPASSWORD=\"\$RDS_PASSWORD\" -v \"\$RDS_CA_BUNDLE:/ca.pem:ro\" postgres:16 psql \"host=\$RDS_HOST user=\$RDS_USER dbname=\$RDS_DB sslmode=verify-full sslrootcert=/ca.pem\" -At -F ,"; }
else
    db() { ssh -i "$APP_KEY" $ssh_opts "$APP" "$compose exec -T postgres sh -c 'psql -U \$POSTGRES_USER -d \$POSTGRES_DB -At -F ,'"; }
fi
vm_now() { app_ssh "date -u +%FT%T.%3NZ"; }
# Stage C: loadtest/queue_depth.py (sent on stdin) in a throwaway container of the worker image on the app host, which has
# boto3 and reaches the instance role: qd_run <container name or ""> depth | purge | sample ...
qd_run() {
    local name=$1; shift
    ssh -i "$APP_KEY" $ssh_opts "$APP" "cd $app_dir && set -a && . ./.env && set +a && img=\$(sudo docker inspect --format '{{.Config.Image}}' \$(sudo docker compose --env-file .env -f $compose_file ps -aq worker | head -1)) && sudo docker run --rm -i ${name:+--name $name} -e SQS_QUEUE_URL=\"\$SQS_QUEUE_URL\" -e AWS_DEFAULT_REGION=\"\${AWS_DEFAULT_REGION:-ap-south-1}\" \"\$img\" python - $*" < "$root/loadtest/queue_depth.py"
}
qd_csv=""; qdpid=""
stop_sampler() {
    [ -n "$qdpid" ] || return 0
    app_ssh "sudo docker stop qdepth-$tag" > /dev/null 2>&1
    kill $qdpid 2>/dev/null; wait $qdpid 2>/dev/null; qdpid=""
}

if [ -z "${COLLECT_ONLY:-}" ]; then
    # ---- 1. checks, made from the generator box (the path the run will use) -----------------
    net=$(mktemp)
    if [ "$c_mode" = 1 ]; then
        {
            echo "checks for Stage C (API on the app host, IoT endpoint and certificate files from the generator box):"
            echo "GET /health: $(app_ssh "curl -s -m 5 http://localhost:8000/health" 2>&1)"
            if oracle_ssh "timeout 5 bash -c 'exec 3<>/dev/tcp/$IOT_ENDPOINT/8883'" 2>/dev/null; then echo "IoT port 8883: open"
            else echo "IoT port 8883: NOT reachable"; fi
            if oracle_ssh "cd $IOT_CERT_DIR && test -r $IOT_CA && test -r $IOT_CERT && test -r $IOT_KEY" 2>/dev/null; then echo "certificate files: readable"
            else echo "certificate files: NOT readable"; fi
            echo "containers running on the app host:"
            app_ssh "$compose ps --status running --format '{{.Service}}'" 2>&1 | sort | tr '\n' ' '; echo
            echo "app host memory (MiB) and load:"
            app_ssh "free -m | sed -n '1,2p'; uptime" 2>&1
        } > "$net" 2>&1
        fail=""
        grep -q '"status":"ok"' <<< "$(grep '^GET /health' "$net")" || fail="the API does not answer /health on the app host (RDS reachable?)"
        if [ -z "$fail" ] && grep -q "NOT reachable" "$net"; then fail="IoT port 8883 is not reachable from the generator box"; fi
        if [ -z "$fail" ] && grep -q "NOT readable" "$net"; then fail="certificate files $IOT_CA, $IOT_CERT, $IOT_KEY are not readable in $IOT_CERT_DIR on the generator box"; fi
        if [ -z "$fail" ]; then
            running=$(grep -A1 '^containers running' "$net" | tail -1)
            for svc in api worker; do grep -qw "$svc" <<< "$running" || fail="container $svc is not running on the app host"; done
            for svc in mosquitto postgres; do grep -qw "$svc" <<< "$running" && fail="container $svc is running: that is a Stage B stack, Stage C has no $svc"; done
        fi
        # the queue and the database must be clean before every measured run
        if [ -z "$fail" ] && [ "${PURGE:-}" = 1 ]; then
            echo "purging the queue (AWS needs up to 60 s) ..." >&2
            qd_run "" purge >&2 || fail="the queue is not empty after the purge (or the instance role lacks sqs:PurgeQueue)"
        fi
        if [ -z "$fail" ]; then
            depth=$(qd_run "" depth 2>/dev/null | tail -1)
            [ "$depth" = "0 0" ] || fail="the queue is not empty (visible, not visible: ${depth:-unknown}); empty it first (console, or PURGE=1)"
        fi
        if [ -z "$fail" ]; then
            leftovers=$(echo "SELECT count(*) FROM readings WHERE device_id LIKE 'it-%';" | db 2>/dev/null | tr -d '[:space:]')
            [ "$leftovers" = 0 ] || fail="the database holds ${leftovers:-an unknown number of} it-% rows (integration test leftovers); delete them first"
        fi
    else
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
    fi
    if [ -n "$fail" ]; then echo "preflight FAILED: $fail" >&2; cat "$net" >&2; rm -f "$net"; exit 1; fi

    # ---- 2. run on the Oracle box -----------------------------------------------------------
    c_opts=""
    if [ "$proto" = http ]; then wrapper="./loadtest/run_http.sh $stage $rate $repeat http://$target:8000"
    elif [ "$c_mode" = 1 ]; then
        wrapper="./loadtest/run_mqtt.sh $stage $rate $repeat $IOT_ENDPOINT 8883"
        c_opts="-v $IOT_CERT_DIR:/work/certs:ro -e CAFILE=/work/certs/$IOT_CA -e CERTFILE=/work/certs/$IOT_CERT -e KEYFILE=/work/certs/$IOT_KEY -e TOPIC_PREFIX=mini-hs/vitals -e CLIENT_ID_PREFIX=mini-hs-device"
    else wrapper="./loadtest/run_mqtt.sh $stage $rate $repeat $target"; fi
    if [ "$c_mode" = 1 ]; then   # queue depth every 5 s on the app host's clock, from before the first message until drained
        trap stop_sampler EXIT
        qd_csv=$(mktemp)
        qd_run "qdepth-$tag" sample --interval 5 --max-seconds $(( ${DRAIN_MAX_S:-900} + 600 )) > "$qd_csv" 2> "$qd_csv.err" & qdpid=$!
        for _ in $(seq 1 30); do [ "$(wc -l < "$qd_csv")" -ge 2 ] && break; sleep 1; done
        [ "$(wc -l < "$qd_csv")" -ge 2 ] || { echo "queue sampler did not start:" >&2; cat "$qd_csv.err" >&2; exit 1; }
    fi
    vm=$(mktemp); ssh -n -i "$APP_KEY" $ssh_opts "$APP" "vmstat -n 5" > "$vm" 2>&1 & vmpid=$!
    oracle_ssh "cd ~/$box && docker run --rm --network host --user \$(id -u):\$(id -g) \
        -e OUT_ROOT=/work/$remote_root -e CONNECTIONS=${CONNECTIONS:-1} -e STAGE_NAME=${STAGE_NAME:-} -e RUN_NOTE=${RUN_NOTE:-} ${DURATION:+-e DURATION=$DURATION} -v \$PWD/loadtest:/work/loadtest:ro -v \$PWD/results:/work/results $c_opts \
        -v \$PWD/calibration:/work/calibration it457-loadgen $wrapper > /dev/null 2>&1"
    gen_rc=$?
    kill $vmpid 2>/dev/null; wait $vmpid 2>/dev/null
    if [ "$c_mode" = 1 ]; then   # wait until the queue has been empty for 3 samples after the generator stopped
        gen_end=$(vm_now); waited_from=$SECONDS; drain_line="queue did not drain within ${DRAIN_MAX_S:-900} s"
        while [ $((SECONDS - waited_from)) -lt "${DRAIN_MAX_S:-900}" ]; do
            if [ "$(awk -F, -v t="$gen_end" 'NR > 1 && $1 > t' "$qd_csv" | tail -n 3 | grep -c ',0,0$')" -eq 3 ]; then
                drain_line="queue drained after $((SECONDS - waited_from)) s"; break
            fi
            sleep 5
        done
        stop_sampler
    fi
    name=$(oracle_ssh "ls -1t ~/$box/$remote_root | grep '^[0-9-]*_${suffix}\$' | head -1")
    [ -n "$name" ] || { echo "generator produced no run folder (exit $gen_rc)" >&2; exit 1; }
else
    name=$COLLECT_ONLY; net=""; vm=""
fi

# ---- 3. copy the raw folder back, never overwrite ----------------------------------------------
dest="$local_root/$name"
if [ -e "$dest" ]; then echo "refusing to reuse $dest (raw results are never overwritten)" >&2; exit 1; fi
mkdir -p "$dest"
rsync -a -e "ssh -i '$ORACLE_KEY' $ssh_opts" "$ORACLE:$box/$remote_root/$name/" "$dest/" || { echo "copy failed" >&2; exit 1; }
if [ -n "$net" ]; then   # the machines' public addresses stay out of the repo (docs/DEPLOYMENT.md)
    content=$(<"$net")
    content=${content//${ORACLE#*@}/<oracle-ip>}; content=${content//$target/<app-ip>}
    [ "$c_mode" = 1 ] && content=${content//$IOT_ENDPOINT/<iot-endpoint>}
    printf '%s\n' "$content" > "$dest/network_check.txt"; rm -f "$net"
fi
[ -n "$vm" ] && mv "$vm" "$dest/app_vmstat.txt"
if [ -n "$qd_csv" ]; then mv "$qd_csv" "$dest/queue_depth.csv"; rm -f "$qd_csv.err"; fi
if [ "$c_mode" = 1 ]; then   # the IoT endpoint is account-specific: keep it out of the tracked settings.json and the other files
    sed -i "s/$IOT_ENDPOINT/<iot-endpoint>/g" "$dest/settings.json" "$dest/ping.txt"
    sed -i -E 's/\(([0-9]{1,3}\.){3}[0-9]{1,3}\)/(<ip>)/' "$dest/ping.txt"
fi

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
if [ "$c_mode" = 1 ]; then
    echo "rows with stored_at NULL: $((${stored:-0} - ${with_stored:-0}))" >> "$dest/db_summary.txt"
    [ -n "${drain_line:-}" ] && echo "$drain_line" >> "$dest/db_summary.txt"
fi
cat "$dest/db_summary.txt"
