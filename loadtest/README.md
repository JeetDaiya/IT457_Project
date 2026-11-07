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

# Load generator (MQTT)

Same rules as above (Oracle machine, run from the repo root). `loadtest/requirements.txt`
also installs `paho-mqtt` (pinned `<2`, the same as the app).

## Calibrate first (generator alone)

```bash
python loadtest/stub_mqtt_broker.py --port 1884 &   # fake broker: PUBACK after 0.22 s (--delay)
OUT_ROOT=loadtest/calibration ./loadtest/run_mqtt.sh cal 500 1 127.0.0.1 1884
```

Read `generator_summary.json` in the run folder. The 500/s rule is the same as for HTTP
(`meets_rate_rule`); if it is false, report the real `achieved_rate`, never 500. If one
connection is the limit, try `CONNECTIONS=4` (several connections, each device stays on one).

## Measured run

```bash
./loadtest/run_mqtt.sh <stage> <rate> <repeat> <broker-host> [port]   # port defaults to 1883
```

Creates `results/<date>_<stage>_mqtt_<rate>_r<repeat>/` (refuses to reuse one) with the same
files as the HTTP run (`ping.txt`, `settings.json`, `generator_log.csv`,
`generator_summary.json`, which also has `connections`). `DURATION=<s>` and `CONNECTIONS=<n>`
override the defaults (2 minutes, 1 connection). The tag is `<stage>m<rate>r<repeat>`, e.g.
`am100r2-dev-0007`. `ok` means the **broker** acknowledged the message (PUBACK); the worker
and the database are not part of that round trip.

## Check a run against the database

`ok` only proves the broker got the message, so compare it with what was stored (Stage A):

```bash
docker compose --env-file .env -f infra/docker-compose.yml exec postgres \
  psql -U healthsuite -d healthsuite -c "
SELECT device_id, count(*) AS stored,
       (max(seq) - min(seq) + 1) - count(DISTINCT seq) AS lost
FROM readings WHERE device_id LIKE 'am10r1-%' GROUP BY device_id ORDER BY device_id;"
```

`lost` is the per-device gap formula; also check that the total of `stored` equals the
generator's `ok` count, because a lost final message leaves no gap.
