# Deployment

## Currently running AWS resources

One team-owned EC2 instance in **Mumbai (`ap-south-1`)** with the Stage B Compose stack (see Stage B below), **stopped at the end of every session by whoever started it** (last start 2026-11-13, for the restart test and the integration tests; check the console). While stopped it still bills its EBS disk (gp3, about 20 GB, about $0.06 a day). Its public IP changes on every start, and the containers do not auto-start (`docker compose up -d`). Nothing in `us-east-1` yet. Stage A ran locally via Docker Compose.

Stage C services, all in Mumbai and created 2026-11-13/14 (details under Stage C below): RDS `mini-hs-db` (PostgreSQL 16.11, `db.t4g.micro`, 20 GiB gp3; **bills about $0.025/hour while running, stop it when idle; AWS restarts a stopped instance after 7 days**), SQS queue `mini-hs-readings`, IAM roles `mini-hs-iot-to-sqs-role` and `mini-hs-ec2-worker-role`, IoT Core policy, certificate and rule, security group `mini-hs-rds-sg`. Only RDS (and the EC2) bill by the hour; the rest cost nothing until messages flow. Stop or delete them after the measurements.

## Load generator (Oracle Cloud Always Free, outside AWS)

- Oracle ARM instance in Mumbai: aarch64, 2 cores, ~12 GB RAM, Ubuntu 24.04, Docker installed. It is shared with other projects (`~/app`, `~/pr-review-agent`); do not touch those.
- Ours lives in `~/it457-loadgen/` (`loadtest/`, `results/`, `calibration/`) plus the Docker image `it457-loadgen`. Nothing is installed on the host and no system setting was changed. Build and run steps are in `loadtest/README.md`.
- The IP address and SSH key are not kept in the repo; use `<oracle-ip>` in docs and scripts.
- **Currently running on Oracle:** one container, `it457-tailscale` (the Tailscale link to the Stage A laptop, below); no load is running. Not an AWS cost.
- **Calibration (2026-11-10, generator alone against the 0.22 s stubs, 2 min):** HTTP and MQTT (1 connection) both reached 500 msg/s (`meets_rate_rule` true, 60,000 of 60,000 acknowledged, p99 schedule lag about 1 ms for HTTP and 0.2 ms for MQTT). Raw output is in `~/it457-loadgen/calibration/` on the box, not in `results/`.

### How Oracle reaches Stage A (Tailscale)

The Stage A laptop is behind Jio carrier-grade NAT (router WAN address `10.3.x.x`, public address shared), so Oracle cannot connect to it directly and a port forward is impossible. Both machines join one personal Tailscale network instead.

- **Account:** a personal one (not a university account; see `GOTCHAS.md`). Both machines show as `jeet.a.daiya24@`.
- **Laptop:** Tailscale installed from the official apt repository; `sudo tailscale up --accept-dns=false`. Its address is `tailscale ip -4`; put that in `.env` as `BIND_IP` so Compose publishes only the API (8000) and MQTT (1883) on it.
- **Oracle:** container `it457-tailscale` (`--network host`, `NET_ADMIN`, `NET_RAW`, `/dev/net/tun`, state in `~/it457-loadgen/tailscale-state/`). It adds the `tailscale0` interface and the `ts-input` / `ts-forward` chains in `iptables-legacy`; DNS and the SSH rules are untouched. Remove with `docker rm -f it457-tailscale` and `sudo rm -rf ~/it457-loadgen/tailscale-state`.
- **Link check (2026-11-10):** the path is direct (not via a relay), about 15 ms round trip when the laptop's Wi-Fi is good. The generator targets `http://<laptop-tailscale-ip>:8000` and `<laptop-tailscale-ip>:1883`, and `ping` to that address works, so `ping.txt` is a real baseline.

## Stage A (local)

- `infra/docker-compose.yml`: PostgreSQL, Mosquitto, `api` and `worker` containers.
- Setup: `cp .env.example .env`, then from the repo root:
  `docker compose --env-file .env -f infra/docker-compose.yml up --build`
- Stop with `docker compose --env-file .env -f infra/docker-compose.yml down` (add `-v` to wipe the data volumes).
- Ports on the host: 8000 (API), 1883 (MQTT), 5432 (Postgres; set `POSTGRES_HOST_PORT` if a local PostgreSQL uses it). 8000 and 1883 are published on `BIND_IP` (default all interfaces; on the laptop set it to the Tailscale address, after which `localhost:8000` no longer answers, so use that address for local checks and for `TEST_BASE_URL`). Postgres (5432) is published on `127.0.0.1` only (weak default password, shared home Wi-Fi).

## Stage B (EC2)

Same Compose file as Stage A. **Deployed 2026-11-12 on the team's EC2 instance in Mumbai (`ap-south-1`)**, not `us-east-1`: Ubuntu 24.04, x86_64, 2 vCPUs, 1.9 GiB RAM, 19 GB disk, Docker Engine and Compose plugin from Docker's apt repository (`ubuntu` is in the `docker` group after the next login; until then use `sudo docker`). The Oracle generator is also in Mumbai, so the generator-to-app path is short (a few ms, not the 200-250 ms planned for `us-east-1`); label every Stage B number accordingly (see `RESULTS.md`).

- **On the VM:** repo cloned to `~/IT457_Project` (main), `.env` created from `.env.example` with a generated Postgres password (mode 600, never committed), then `sudo docker compose --env-file .env -f infra/docker-compose.yml up -d --build`. `curl localhost:8000/health` answers `{"status":"ok"}`; Postgres is published on `127.0.0.1` only. The SSH key and the IPs stay out of the repo (`<ec2-ip>`, `<oracle-ip>`).
- **Security group (inbound), only from the Oracle IP (`/32`):** TCP 8000, TCP 1883, and **ICMP echo** (otherwise `ping.txt` says "ping failed or is blocked", see `GOTCHAS.md`). SSH (22) only from the team's own addresses. Do **not** open 5432. Anonymous MQTT (1883) is acceptable only with that source restriction.
- **Integration tests on the VM (passed 2026-11-13, 11 of 11, 4.6 s):** no Python tools on the VM, so from `~/IT457_Project` (stack up, no load running) with `.env` sourced (`set -a; . ./.env; set +a`):
  `sudo docker run --rm --network host -v "$PWD":/app:ro -w /app -e PYTHONDONTWRITEBYTECODE=1 -e TEST_BASE_URL=http://localhost:8000 -e TEST_MQTT_HOST=localhost -e TEST_MQTT_PORT=1883 -e TEST_DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB" python:3.12-slim sh -c "pip install -q -r requirements.txt pytest httpx && python -m pytest -m integration tests/integration -p no:cacheprovider"`.
  The password stays on the VM (the URL form needs a letters-and-digits password, as the generated one is). Count `it-%` rows before and after (expect 0).
- **RAM is tight (1.9 GiB):** watch `app_vmstat.txt` in each run folder; add a swap file before the 500 msg/s steps if memory runs out.
- **Measured runs:** `loadtest/measure_run_remote.sh` (README section "Stage B"), run from the laptop; it reads the database over SSH on the VM.
- **Open:** whether this is the final Stage B or a dry run before a `us-east-1` instance (team decision). Stage B cost (list price) is in `RESULTS.md`.

## Stage C (EC2 + managed services)

The app (`api` and `worker`) stays on the Mumbai EC2; the database is RDS and the input is an IoT Core rule that puts every device message into SQS. Placeholders: `<rds-endpoint>`, `<iot-endpoint>`, `<account-id>`, `<ec2-ip>`; the master password, the IoT private key and the IPs are never committed.

- **RDS `mini-hs-db`:** PostgreSQL 16.11 (same major version as the Stage A/B container), `db.t4g.micro` (2 vCPUs, 1 GiB), gp3 20 GiB with autoscaling off, single-AZ, **not publicly accessible**, in the same VPC as the EC2 (`Baadal-vpc`), database `minihs`, user `postgres` (password self-managed, kept in `.env` on the VM only), encryption on, 1 day of automated backups, Enhanced Monitoring off, Database Insights Standard, deletion protection off. **`max_connections` is 79** (Stage B's container allowed 100), about 70 usable; `app/db.py` currently sizes each process's pool at up to 40, so the `api` and `worker` pools together can reach the limit and need to be sized down.
- **`mini-hs-rds-sg`:** inbound PostgreSQL 5432 only from the EC2's security group (by group, not by IP, so it keeps working after a restart). Nothing reaches the database from the internet or the laptop; use `psql` from the EC2.
- **TLS to RDS:** `sslmode=verify-full` with AWS's public CA bundle (`global-bundle.pem`, downloaded to the VM's home directory and mounted into the containers). `psql` checked 2026-11-13: PostgreSQL 16.11.
- **SQS `mini-hs-readings`:** Standard, visibility timeout 30 s, retention 4 days, queue-level long polling 20 s, server-side encryption (SSE-SQS). **No dead-letter queue yet (open decision):** a message the worker cannot process comes back after every 30 s for 4 days otherwise. Standard means duplicates and out-of-order delivery are possible; `UNIQUE (device_id, seq)` is the guard.
- **IoT Core:** policy `mini-hs-device-policy` (Connect only for client IDs `mini-hs-device-*`, Publish only on `mini-hs/vitals/*`, no Subscribe), one shared certificate for all simulated devices (a test simplification; each connection still needs its own client ID), endpoint `<iot-endpoint>` on port 8883 (mutual TLS, no plain 1883). Rule `mini_hs_vitals_to_sqs`: `SELECT * FROM 'mini-hs/vitals/+'`, so the SQS body is the device JSON unchanged. A console test message reached the queue (2026-11-13).
- **IAM (least privilege):** `mini-hs-iot-to-sqs-role` (trusted by `iot.amazonaws.com`) may only `sqs:SendMessage` on the queue. `mini-hs-ec2-worker-role` is the EC2's instance role and may only `sqs:ReceiveMessage`, `sqs:DeleteMessage` and `sqs:GetQueueAttributes` on the queue: no keys are stored anywhere. IMDSv2 is required with **hop limit 2**, so containers can read the role's credentials (the default of 1 blocks them). Checked from a container 2026-11-14: `sts get-caller-identity` shows the role, receive works, `SendMessage` is denied.
- **Run it:** on the VM, in `~/IT457_Project`, stop the Stage B stack first (`docker compose --env-file .env -f infra/docker-compose.yml down`, no `-v`: the volume holds the Stage B rows), add to `.env` `RDS_HOST`, `RDS_USER`, `RDS_PASSWORD`, `RDS_DB`, `SQS_QUEUE_URL` and `RDS_CA_BUNDLE` (full path; the password must be letters and digits only because it goes into a URL), then `sudo docker compose --env-file .env -f infra/docker-compose.stage-c.yml up -d --build`. Both containers stay up, `curl localhost:8000/health` answers `{"status":"ok"}` (so the `api` reached RDS and created the tables) and the worker logs `polling SQS queue` (checked 2026-11-14). Nothing has yet gone through the whole IoT-to-RDS path from a real generator run.
- **Gotchas found on the VM:** under `sudo`, `${HOME}` is `/root`, so a default of `~/global-bundle.pem` makes Docker mount an empty directory and the app fails with "could not read root certificate file ... no certificate or crl found" (hence no default for `RDS_CA_BUNDLE`); the Stage B containers (`infra-postgres-1`, `infra-mosquitto-1`) stay as orphans of the shared project name `infra`: leave them, and stop Stage C before starting Stage B again.
- **Open:** DLQ yes or no; pool sizes against `max_connections` 79; Stage C hours and cost to be recorded when the runs finish (so far: on 2026-11-14 the EC2 and RDS each ran about 30 minutes, 11:54 to 12:38 IST session, for the first start of the Stage C stack).
