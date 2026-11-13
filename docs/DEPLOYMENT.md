# Deployment

## Currently running AWS resources

One team-owned EC2 instance in **Mumbai (`ap-south-1`)** with the Stage B Compose stack (see Stage B below), **stopped at the end of every session by whoever started it** (last start 2026-11-13, for the restart test and the integration tests; check the console). While stopped it still bills its EBS disk (gp3, about 20 GB, about $0.06 a day). Its public IP changes on every start, and the containers do not auto-start (`docker compose up -d`). Nothing in `us-east-1` yet. Stage A ran locally via Docker Compose.

The team is setting up Stage C services ahead of time in Mumbai. SQS, S3, Glue, Secrets Manager and RDS lines appear on the bill at $0.00 so far. The exact resources are not listed here yet: add them (and stop or delete them after the measurements) when known.

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

_Not yet deployed._
