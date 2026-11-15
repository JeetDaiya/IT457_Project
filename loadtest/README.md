# Running on the Oracle box (container)

The box (aarch64, 2 cores, Ubuntu 24.04, Docker installed) has no `python3.12-venv` and also hosts
other projects, so the generator runs in a container and nothing is installed on the host. The image
(`loadtest/Dockerfile`) holds only Python 3.12, Locust, paho-mqtt and `ping`. `loadtest/` is mounted
read-only and `results/` read-write, so a script fix needs a re-push but no rebuild.

Push the code from the repo root on your machine (`<oracle-ip>` and the key are not kept in the repo):

```bash
rsync -a --delete --exclude __pycache__ --exclude calibration \
  -e "ssh -i <key>" loadtest/ ubuntu@<oracle-ip>:it457-loadgen/loadtest/
```

On the box, build once (again only after `requirements.txt` or the Dockerfile changes):

```bash
cd ~/it457-loadgen && mkdir -p results calibration
docker build -f loadtest/Dockerfile -t it457-loadgen .
RUN="docker run --rm --network host --user $(id -u):$(id -g) \
  -v $PWD/loadtest:/work/loadtest:ro -v $PWD/results:/work/results \
  -v $PWD/calibration:/work/calibration it457-loadgen"
```

Then use `$RUN` in front of the wrappers described below:

```bash
$RUN ./loadtest/run_http.sh <stage> <rate> <repeat> http://<app-host>:8000
$RUN ./loadtest/run_mqtt.sh <stage> <rate> <repeat> <broker-host> [port]
```

Calibration on the box (the stub and the generator both use `--network host`, so `127.0.0.1` works;
output goes to `calibration/`, not `results/`):

```bash
docker run -d --rm --name loadgen-stub --network host --user $(id -u):$(id -g) \
  -v $PWD/loadtest:/work/loadtest:ro it457-loadgen python loadtest/stub_server.py --port 9000
$RUN env OUT_ROOT=/work/calibration ./loadtest/run_http.sh cal 500 1 http://127.0.0.1:9000
docker stop loadgen-stub
```

For MQTT, start `python loadtest/stub_mqtt_broker.py --port 1884` the same way and run
`$RUN env OUT_ROOT=/work/calibration ./loadtest/run_mqtt.sh cal 500 1 127.0.0.1 1884`.

Why it is built this way:
- `--network host`: no Docker NAT in the path, and `ping.txt` measures the real route from the box.
- `--user`: files in `results/` belong to `ubuntu`, not root. `ping` still works because the Dockerfile
  gives it `cap_net_raw` (the host disables unprivileged ICMP and the Debian 13 package no longer sets it).
- Remove everything with `docker rmi it457-loadgen` and `rm -rf ~/it457-loadgen`.

Checked on the box: image build, imports, `ping` as non-root, writing to `results/` and `calibration/`,
and the stub answering 201 after about 0.22 s. Calibration (2026-11-10): HTTP and MQTT both reached 500 msg/s for 2 minutes against the stubs.

To run against Stage A on the laptop, use its Tailscale address as the host (see `docs/DEPLOYMENT.md`), for example
`$RUN ./loadtest/run_http.sh a 100 1 http://<laptop-tailscale-ip>:8000`. For a short smoke test use stage `smoke` and `-e DURATION=30 -e OUT_ROOT=/work/calibration`, so the run tags cannot collide with measured runs and `results/` stays clean.

# Measured runs from the machine that hosts the stack (`measure_run.sh`)

One command per run, started on the laptop (Stage A) and driving the Oracle box over SSH:

```bash
ORACLE=ubuntu@<oracle-ip> SSH_KEY=<key> ./loadtest/measure_run.sh <http|mqtt> <rate> <repeat>
```

It (1) checks the network and stops without sending anything if it is bad, (2) runs the generator in the
container on the box, (3) copies the raw run folder to `results/<date>_<Stage>_<kind>_<rate>per-s_run<n>/` (never
overwrites; the date is the box's UTC date), (4) waits until the stored row count stops changing, (5) saves the
database numbers in `db_summary.txt` and appends one line to `results/summary.csv`.

- **Preflight:** router ping average <= 10 ms and maximum <= 50 ms (20 pings, 0.2 s apart), Wi-Fi signal >= -70 dBm,
  a direct (not relayed) Tailscale path to the box, and the API answering on the target. Also turn Wi-Fi power
  save off (see `docs/GOTCHAS.md`).
- **Files in each run folder:** `settings.json`, `ping.txt`, `generator_log.csv`, `generator_summary.json`,
  `network_check.txt` (the box's public address is replaced with `<oracle-ip>` before it is saved),
  `laptop_vmstat.txt` (laptop CPU every 5 s), `db_summary.txt`.
- **`summary.csv` columns:** `avg_delay_ms` and `p95_delay_ms` are *server time* (`stored_at - received_at`);
  `lost_readings` is the per-device formula; `notes` holds the client round trip (avg and p95 from the generator's
  clock), the baseline ping average, `ok`, achieved rate, `stored` and `missing` (readings sent minus rows stored,
  which also sees losses at the end of a device's sequence).
- **Env:** `STAGE` (default `a`; the run tag is `<stage><h|m><rate>r<repeat>`), `CONNECTIONS` (MQTT connections,
  default 1; the Stage A MQTT runs after the first matrix use 100, one per simulated device), `TARGET`, `ORACLE_TS_IP`,
  `REMOTE_ROOT`, `LOCAL_ROOT`, `COLLECT_ONLY=<run folder>` (collect an existing run from the box without running).
- **Folder names** come from `loadtest/run_name.sh`: `<date>_<Stage>_<kind>_<rate>per-s_run<n>`, where kind is `http` or
  `mqtt-<N>conn` (with `-<RUN_NOTE>` appended when set, for example `-restart`). A one-letter stage is upper-cased
  (`a` becomes `A`). `STAGE_NAME` overrides the stage shown in the folder name.
- **Database tag vs folder name:** the stage argument (`STAGE`) still goes into the run tag (`device_id` prefix), and a
  repeated tag would silently drop rows (`UNIQUE (device_id, seq)`). So use a different `STAGE` for a variant of the
  same stage, protocol, rate and repeat, and set `STAGE_NAME=A` so the folder still says Stage A. Stage A used `a`
  (first matrix, MQTT on 1 connection), `aconn100` (12 MQTT runs on 100 connections) and `arestart`; `results/name_map.csv`
  lists each folder's old name and database tag. `smoke` and `cal` runs go to `calibration/`.

Restart test (MQTT, worker stopped in the middle; same SSH variables):

```bash
ORACLE=ubuntu@<oracle-ip> SSH_KEY=<key> ./loadtest/restart_test.sh <repeat> [rate=100] [stop_after_s=40] [down_s=20]
```

It runs `measure_run.sh` with `STAGE=arestart` (tag), `STAGE_NAME=A` and `RUN_NOTE=restart` (folder), stops the worker `stop_after_s` after the first reading is stored,
starts it `down_s` later, and adds `worker_restart.txt` (UTC times), `restart_summary.txt` (sent, stored, missing,
longest gap between `stored_at` values) and `stored_per_second.csv` (backlog drain) to the run folder. The worker is
always started again, even if the run fails. `docker compose stop` waits 10 s before killing the worker, so the real
outage starts when `stop_returned` is logged.

After new runs, refresh the compact stats and the result tables (see `results/README.md` for what is in git and what is archived):

```bash
python loadtest/result_tables.py stats results            # raw run folders -> results/run_stats.csv, restart_stats.csv
python loadtest/result_tables.py results docs/RESULTS.md   # those two files -> the tables in docs/RESULTS.md
```

`run_stats.csv` has one line per run, including sent, stored and missing; lines of runs whose folder is no longer on
this machine are kept. Then zip the new run folders into the team Drive archive and record the checksum.

# Stage B: the stack runs on a remote VM (`measure_run_remote.sh`)

`measure_run.sh` assumes the stack runs on the machine you start it on (Stage A). When the stack runs on the EC2 box,
start `measure_run_remote.sh` from any control machine (the laptop). It drives the Oracle generator and the app host over SSH:

```bash
ORACLE=ubuntu@<oracle-ip> ORACLE_KEY=<key> APP=ubuntu@<ec2-ip> APP_KEY=<key> \
  ./loadtest/measure_run_remote.sh <http|mqtt> <rate> <repeat>
```

- **Preflight (from the generator box, the path the run uses):** `GET /health` answers `{"status":"ok"}`, for MQTT port 1883 is
  open, and the four containers (`api`, `mosquitto`, `postgres`, `worker`) run on the app host. Otherwise it stops before
  sending anything. The result, five `/health` times and the app host's memory are saved in `network_check.txt`
  (both public addresses replaced by `<oracle-ip>` and `<app-ip>`). There is no Wi-Fi or Tailscale check.
- **Run, copy back, database numbers, `summary.csv`:** as for `measure_run.sh`. The database is read with
  `ssh <app> sudo docker compose ... exec -T postgres psql`, so `APP_DIR` (default `IT457_Project`, relative to the VM user's
  home) must point at the repo with the `.env` of the running stack, and the VM user needs passwordless `sudo`.
- **Different files:** `app_vmstat.txt` (VM CPU and memory every 5 s) instead of `laptop_vmstat.txt`.
- **Env:** `STAGE` defaults to `b` (tag `<stage><h|m><rate>r<repeat>`; folder `<date>_B_...`), `TARGET` (host the generator
  calls, default the host part of `APP`), `CONNECTIONS`, `STAGE_NAME`, `RUN_NOTE`, `APP_DIR`, `REMOTE_ROOT`, `LOCAL_ROOT`,
  `COLLECT_ONLY=<run folder>`.
- **Needs in the security group:** TCP 8000 and 1883 and ICMP echo from the Oracle IP (see `docs/DEPLOYMENT.md`).
- **Server time** is `stored_at - received_at` on the VM's clock; the client round trip and ping use the generator's clock. Never subtract across machines.
- **Restart test on the VM:** `restart_test_remote.sh` is the remote version of `restart_test.sh`:
  `ORACLE=... ORACLE_KEY=... APP=... APP_KEY=... ./loadtest/restart_test_remote.sh <repeat> [rate=100] [stop_after_s=40] [down_s=20]`.
  It runs `measure_run_remote.sh` for MQTT with `STAGE=brestart` (tag `brestartm<rate>r<repeat>`), `STAGE_NAME=B` and `RUN_NOTE=restart`
  (folder `<date>_B_mqtt-100conn-restart_...`), stops and starts the worker over SSH, and adds the same three files as the Stage A
  version. Its step timestamps are taken on the VM, the clock of `stored_at`. The worker is always started again, even if the run fails.

# Stage C: IoT Core, SQS, RDS (`STAGE_C=1`)

The same two scripts, MQTT only, with `STAGE_C=1`. Without it nothing changes for Stages A and B. The generator publishes over TLS
(port 8883, one device certificate shared by all connections) to AWS IoT Core; an IoT rule puts each message in SQS and the worker on
the EC2 stores it in RDS.

```bash
STAGE_C=1 IOT_ENDPOINT=<device-data-endpoint> IOT_CERT_DIR=/home/ubuntu/iot-certs \
  IOT_CA=AmazonRootCA1.pem IOT_CERT=device.crt IOT_KEY=device.key \
  ORACLE=ubuntu@<oracle-ip> ORACLE_KEY=<key> APP=ubuntu@<ec2-ip> APP_KEY=<key> \
  ./loadtest/measure_run_remote.sh mqtt <rate> <repeat>        # or restart_test_remote.sh <repeat>
```

- **Certificates stay on the Oracle box** (`IOT_CERT_DIR`, absolute path, private key mode 600, mounted read-only in the generator container). They
  are never copied back or committed. Get the endpoint under IoT Core, Settings, Device data endpoint.
- **Short runs:** `DURATION=<seconds>` (default 120) is passed to the generator; the 30 s check used `STAGE=ccheck RUN_NOTE=check DURATION=30` so it does not share a tag or folder name with measured runs.
- **Defaults in this mode:** `STAGE=c` (tag `cm<rate>r<n>`; restart test `crestart`), folder `<date>_C_mqtt-100conn_...`, 100 connections.
  The generator uses client IDs `mini-hs-device-1..N` and topics `mini-hs/vitals/<device_id>` (the IoT policy and the rule
  `SELECT * FROM 'mini-hs/vitals/+'` allow only those). Client IDs must be unique per connection: **never run two generators at once.**
  With TLS the generator refuses to start when `connections < rate / 100` (IoT Core allows 100 publishes per second per connection).
- **Before every run (stops with the reason otherwise):** `/health` on the app host (proves RDS is reachable), only `api` and `worker` running,
  port 8883 open and the certificate files readable from the Oracle box, the queue empty (visible and not visible 0) and 0 `it-%` rows in RDS.
  Empty the queue by hand in the console (wait about a minute), or give `mini-hs-ec2-worker-role` the `sqs:PurgeQueue` permission on the queue and
  start with `PURGE=1`. Leftover `it-` rows come from the integration tests (`docs/GOTCHAS.md`).
- **During the run:** `queue_depth.csv` (`time_utc,visible,not_visible`, app host clock) every 5 s from `loadtest/queue_depth.py`, which runs in a
  throwaway container of the worker image so it uses the instance role. After the generator stops the script waits until three samples in a row
  are 0/0 (at most `DRAIN_MAX_S`, default 900) before it reads the database.
- **Database:** RDS is private, so `psql` runs in a `postgres:16` container on the app host (verified TLS, password and CA bundle from the VM's `.env`).
  `db_summary.txt` keeps its lines and adds `rows with stored_at NULL: N` and `queue drained after N s` (or `did not drain within N s`).
- **Redaction:** the IoT endpoint and the addresses are replaced by `<iot-endpoint>`, `<app-ip>` and `<oracle-ip>` in the copies of `settings.json`,
  `ping.txt` and `network_check.txt`; the originals stay on the Oracle box. `settings.json` also records `tls`, `topic_prefix` and `client_id_prefix`.
- **Baseline ping** is a normal `ping` of the IoT endpoint (it answers ICMP from the Oracle box: about 1.4 ms).
- **Restart test:** the same script with the worker stopped for 20 s at 100 msg/s; IoT Core and SQS hold the readings, so expect 0 missing.
- **Worker count:** `WORKERS=<n>` in the app host's `.env` (default 1) sets how many worker containers read the queue (`deploy.replicas` in
  `infra/docker-compose.stage-c.yml`); apply it with `up -d --no-build --no-recreate` on the VM. One worker stores about 100 readings/s (single thread,
  two RDS commits per reading), two about 200/s. The run script records the count (`workers: N` in `db_summary.txt`), so tag and folder for the
  scaling runs carry it: `STAGE=cw2 RUN_NOTE=w2` (tag `cw2m500r<n>`, folder kind `mqtt-100conn-w2`) and `STAGE=cw4 RUN_NOTE=w4`.
- **Stage C measured set** (MQTT only, 100 connections, 120 s, 3 repeats), with `STAGE_C=1`, the `IOT_*` variables, `DRAIN_MAX_S=1800` and `WORKERS=1`:
  `measure_run_remote.sh mqtt <rate> <repeat>` for 10, 50, 100 and 500 msg/s; `restart_test_remote.sh <repeat>`; then `WORKERS=2` and `WORKERS=4` with
  `measure_run_remote.sh mqtt 500 <repeat>` (tags as above). Extra lines in `db_summary.txt`: `workers`, `storing took ... stored per second`, `queue peak`.
  `python loadtest/result_tables.py stats` also writes `results/queue_stats.csv`, and a `<!-- result_tables: queue stage=C kinds=... -->` block in `docs/RESULTS.md` renders it.
- **First use:** a 30 s check at 500 msg/s against IoT Core, after the team lead agrees (stage, protocol, rate, duration), then the measured runs.
- **Generator options** (also usable without the scripts): `--topic-prefix`, `--client-id-prefix`, `--cafile`, `--certfile`, `--keyfile`; or the
  environment variables `TOPIC_PREFIX`, `CLIENT_ID_PREFIX`, `CAFILE`, `CERTFILE`, `KEYFILE` for `run_mqtt.sh`. All are off by default.

# Load generator (HTTP)

Runs on the Oracle ARM machine in Mumbai, never on a machine being migrated. On the Oracle box use
the container described under "Running on the Oracle box" below. For a local run, install with
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

Creates `results/<date>_<Stage>_http_<rate>per-s_run<repeat>/` (refuses to reuse one) with:
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

Creates `results/<date>_<Stage>_mqtt-<N>conn_<rate>per-s_run<repeat>/` (refuses to reuse one) with the same
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
