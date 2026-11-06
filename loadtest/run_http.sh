#!/usr/bin/env bash
# One HTTP run: ./loadtest/run_http.sh <stage> <rate> <repeat> <base-url>
# Env: OUT_ROOT (default results/), DURATION in seconds (default 120), PYTHON (default python).
set -u

if [ $# -ne 4 ]; then
    echo "usage: $0 <stage> <rate> <repeat> <base-url>" >&2
    exit 2
fi
stage=$1 rate=$2 repeat=$3 url=$4

root=$(cd "$(dirname "$0")/.." && pwd)
out="${OUT_ROOT:-$root/results}/$(date +%F)_${stage}_http_${rate}_r${repeat}"
if [ -e "$out" ]; then
    echo "refusing to reuse $out (raw results are never overwritten)" >&2
    exit 1
fi
mkdir -p "$out"

host=${url#*://}
host=${host%%[:/]*}
ping -c 20 -q "$host" > "$out/ping.txt" 2>&1 || echo "ping failed or is blocked" >> "$out/ping.txt"

cd "$root" && "${PYTHON:-python}" -m locust -f loadtest/locustfile.py --headless -u 1 -r 1 \
    --only-summary --host "$url" --rate "$rate" --duration "${DURATION:-120}" \
    --tag "${stage}h${rate}r${repeat}" --out-dir "$out"
