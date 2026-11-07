# Load generator (HTTP)

Runs on the Oracle ARM machine in Mumbai, never on a machine being migrated. Install with
`pip install -r loadtest/requirements.txt` (Python 3.12) and run everything from the repo root.

## Calibrate first (generator alone)

```bash
python loadtest/stub_server.py --port 9000 &        # fake app: 201 after 0.22 s
OUT_ROOT=loadtest/calibration ./loadtest/run_http.sh cal 500 1 http://127.0.0.1:9000
```

Read `generator_summary.json` in the run folder. 500/s counts as reached only if
`meets_rate_rule` is true (at least 99% of the target rate and p99 schedule lag under 50 ms).
If not, report the real `achieved_rate`, never 500.

## Measured run

```bash
./loadtest/run_http.sh <stage> <rate> <repeat> http://<app-host>:8000
```

Creates `results/<date>_<stage>_http_<rate>_r<repeat>/` (refuses to reuse one) with:
`ping.txt` (baseline ping, reported separately), `settings.json`, `generator_log.csv`
(`device_id,seq,send_time_utc,result,rtt_ms`) and `generator_summary.json`. `DURATION=<s>`
overrides the 2-minute default. `device_id` carries the run tag, e.g. `ah100r2-dev-0007`.
