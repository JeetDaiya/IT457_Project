#!/usr/bin/env bash
# One measured run, driven from the machine that hosts the stack (Stage A: the laptop).
#   ORACLE=ubuntu@<oracle-ip> SSH_KEY=<key> ./loadtest/measure_run.sh <http|mqtt> <rate> <repeat>
# 1. checks the laptop's Wi-Fi and the Tailscale path (aborts if bad),
# 2. runs the generator on the Oracle box (container, see loadtest/README.md),
# 3. copies the raw run folder back (never overwrites), waits until the worker has finished storing,
# 4. saves the database query output next to it and appends one line to summary.csv.
# Env: STAGE (default a), ORACLE_TS_IP (generator's Tailscale address, default: the online it457-loadgen peer), TARGET (host the generator calls, default `tailscale ip -4`),
#      CONNECTIONS (MQTT connections, default 1), STAGE_NAME / RUN_NOTE (folder name only, see run_name.sh), REMOTE_ROOT (default results), LOCAL_ROOT (default <repo>/results),
#      COLLECT_ONLY=<run folder name> to skip the check and the run and only collect that run.
set -u -o pipefail

if [ $# -ne 3 ] || [ -z "${ORACLE:-}" ] || [ -z "${SSH_KEY:-}" ]; then
    echo "usage: ORACLE=user@host SSH_KEY=<key> $0 <http|mqtt> <rate> <repeat>" >&2
    exit 2
fi
proto=$1 rate=$2 repeat=$3
case $proto in http) letter=h ;; mqtt) letter=m ;; *) echo "protocol must be http or mqtt" >&2; exit 2 ;; esac

root=$(cd "$(dirname "$0")/.." && pwd)
. "$root/loadtest/run_name.sh"
stage=${STAGE:-a}
target=${TARGET:-$(tailscale ip -4 | head -1)}
remote_root=${REMOTE_ROOT:-results}
local_root=${LOCAL_ROOT:-$root/results}
tag="${stage}${letter}${rate}r${repeat}"
suffix=$(run_suffix "$stage" "$proto" "$rate" "$repeat")   # <stage>_<kind>_<rate>per-s_run<n>
ssh_cmd="ssh -i $SSH_KEY -o BatchMode=yes"
remote="$ORACLE"
box=it457-loadgen
psql_cmd=${PSQL:-"docker compose --env-file $root/.env -f $root/infra/docker-compose.yml exec -T postgres sh -c 'psql -U \$POSTGRES_USER -d \$POSTGRES_DB -At -F ,'"}
db() { (cd "$root" && eval "$psql_cmd") ; }

if [ -z "${COLLECT_ONLY:-}" ]; then
    # ---- 1. network check -------------------------------------------------------------------
    gw=$(ip route show default | awk '{print $3; exit}')
    net=$(mktemp)
    {
        echo "router $gw:"; ping -c 20 -i 0.2 -q "$gw" | tail -2
        iw dev wlo1 link 2>/dev/null | grep -E 'freq|signal|tx bitrate'
        # An idle peer shows "-" in `tailscale status`, so wake the path and wait for a direct one.
        peer=${ORACLE_TS_IP:-$(tailscale status | awk '/it457-loadgen/ && !/offline/ {print $1; exit}')}
        echo "tailscale path to the generator ($peer):"
        tailscale ping -c 10 --until-direct --timeout 3s "$peer" 2>&1 | tail -4
    } > "$net" 2>&1
    avg=$(awk -F'[/ =]+' '/^rtt/ {print $7}' "$net"); max=$(awk -F'[/ =]+' '/^rtt/ {print $8}' "$net")
    sig=$(awk '/signal:/ {print $2}' "$net")
    if [ -z "$avg" ] || ! awk -v a="$avg" -v m="$max" -v s="${sig:--99}" 'BEGIN{exit !(a<=10 && m<=50 && s>=-70)}'; then
        echo "network check FAILED (router ping avg ${avg:-?} ms, max ${max:-?} ms, signal ${sig:-?} dBm; need avg<=10, max<=50, signal>=-70)." >&2
        cat "$net" >&2; exit 1
    fi
    if ! grep -qE 'pong from .* via [0-9]' "$net"; then echo "tailscale path is not direct (relayed?); aborting" >&2; cat "$net" >&2; exit 1; fi
    curl -s -m 5 "http://$target:8000/health" >/dev/null || { echo "the API is not answering on $target:8000" >&2; exit 1; }

    # ---- 2. run on the Oracle box -----------------------------------------------------------
    if [ "$proto" = http ]; then wrapper="./loadtest/run_http.sh $stage $rate $repeat http://$target:8000"
    else wrapper="./loadtest/run_mqtt.sh $stage $rate $repeat $target"; fi
    vm=$(mktemp); vmstat -n 5 > "$vm" & vmpid=$!
    $ssh_cmd "$remote" "cd ~/$box && docker run --rm --network host --user \$(id -u):\$(id -g) \
        -e OUT_ROOT=/work/$remote_root -e CONNECTIONS=${CONNECTIONS:-1} -e STAGE_NAME=${STAGE_NAME:-} -e RUN_NOTE=${RUN_NOTE:-} -v \$PWD/loadtest:/work/loadtest:ro -v \$PWD/results:/work/results \
        -v \$PWD/calibration:/work/calibration it457-loadgen $wrapper > /dev/null 2>&1"
    gen_rc=$?
    kill $vmpid 2>/dev/null
    name=$($ssh_cmd "$remote" "ls -1t ~/$box/$remote_root | grep '^[0-9-]*_${suffix}\$' | head -1")
    [ -n "$name" ] || { echo "generator produced no run folder (exit $gen_rc)" >&2; exit 1; }
else
    name=$COLLECT_ONLY; net=""; vm=""
fi

# ---- 3. copy the raw folder back, never overwrite ----------------------------------------------
dest="$local_root/$name"
if [ -e "$dest" ]; then echo "refusing to reuse $dest (raw results are never overwritten)" >&2; exit 1; fi
mkdir -p "$dest"
rsync -a -e "$ssh_cmd" "$remote:$box/$remote_root/$name/" "$dest/" || { echo "copy failed" >&2; exit 1; }
if [ -n "$net" ]; then   # the box's public address stays out of the repo (docs/DEPLOYMENT.md)
    content=$(<"$net"); printf '%s\n' "${content//${ORACLE#*@}/<oracle-ip>}" > "$dest/network_check.txt"; rm -f "$net"
fi
[ -n "$vm" ] && mv "$vm" "$dest/laptop_vmstat.txt"

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
    echo "server time = stored_at - received_at (laptop clock only): avg ${avg_ms} ms, slowest 5% (p95) ${p95_ms} ms"
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
