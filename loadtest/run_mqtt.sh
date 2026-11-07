#!/usr/bin/env bash
# One MQTT run: ./loadtest/run_mqtt.sh <stage> <rate> <repeat> <broker-host> [port]
# Env: OUT_ROOT (default results/), DURATION in seconds (default 120), CONNECTIONS (default 1),
#      PYTHON (default python).
set -u

if [ $# -lt 4 ] || [ $# -gt 5 ]; then
    echo "usage: $0 <stage> <rate> <repeat> <broker-host> [port]" >&2
    exit 2
fi
stage=$1 rate=$2 repeat=$3 host=$4 port=${5:-1883}

root=$(cd "$(dirname "$0")/.." && pwd)
out="${OUT_ROOT:-$root/results}/$(date +%F)_${stage}_mqtt_${rate}_r${repeat}"
if [ -e "$out" ]; then
    echo "refusing to reuse $out (raw results are never overwritten)" >&2
    exit 1
fi
mkdir -p "$out"

ping -c 20 -q "$host" > "$out/ping.txt" 2>&1 || echo "ping failed or is blocked" >> "$out/ping.txt"

cd "$root" && "${PYTHON:-python}" -m loadtest.mqtt_generator --host "$host" --port "$port" \
    --rate "$rate" --duration "${DURATION:-120}" --connections "${CONNECTIONS:-1}" \
    --tag "${stage}m${rate}r${repeat}" --out-dir "$out"
