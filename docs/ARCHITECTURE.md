# Architecture

## Folder layout

```
app/          – FastAPI service (settings, db, rules, api, mqtt_in, main)
infra/        – Dockerfile, docker-compose.yml, mosquitto/ config; AWS scripts/notes later
loadtest/     – Locust and paho-mqtt generator scripts
tests/        – unit/API tests (mocked) and tests/integration (running stack)
results/      – Raw run data, one folder per run, summary.csv
docs/         – Living docs (this file, GOTCHAS, CHANGELOG, etc.)
```

## Layers

```
HTTP (api.py)    ─┐
                  ├─► process_reading() (service.py) ─► ReadingStore port ◄─ PostgresReadingStore (db.py)
MQTT (mqtt_in.py)─┘
```

Dependencies point inward only: `api` / `mqtt_in` → `service` → `rules`, and `settings` → `rules`. `db` implements a port that `service` defines. Only `main.py` knows all the pieces and wires them together.

| Layer | File | Responsibility |
|---|---|---|
| Domain | `app/rules.py` | `Reading` (validation ranges), `Limits`, `is_abnormal()`. Imports nothing from the app |
| Configuration | `app/settings.py` | `Settings` and `load_settings()` (environment → settings); `Settings.limits()` returns `Limits` |
| Application | `app/service.py` | `process_reading()` plus the ports it needs: `ReadingStore`, `Clock` |
| Infrastructure | `app/db.py` | `PostgresReadingStore` (SQLAlchemy Core + psycopg2), schema init, patient seeding, `SystemClock` |
| Interface | `app/api.py` | Thin FastAPI routers: call the injected processor, map outcome → HTTP status |
| Interface | `app/mqtt_in.py` | `run()` subscribes to the topic at QoS 1 (persistent session) and reconnects; `handle_message()` parses, calls the injected processor and never raises. paho sends the ack after it returns |
| Composition | `app/main.py` | Wires settings → store → processor; runs `api` or `worker` mode |

`process_reading()` is the single shared function called by both the HTTP endpoint and the MQTT worker. Stage C adds an SQS queue between IoT Core and the worker; only the worker's input module changes.

## Interfaces (contract between teammates)

**Reading JSON** (synthetic data only; `patient_ref` is a code, never a name):

```json
{"device_id": "dev-0007", "patient_ref": "P0007", "heart_rate": 72, "spo2": 97,
 "temperature": 36.8, "seq": 1042, "sent_at": "2026-11-05T09:15:03.412Z"}
```

Types: `device_id` / `patient_ref` string; `heart_rate` / `spo2` / `seq` integer; `temperature` number; `sent_at` ISO 8601 UTC. `seq` starts at 1 and increases by 1 per message per device (the lost-readings formula depends on this).

**Message size:** the seven fields only, about 170 bytes, with no padding. The original spec said about 0.5 KB; we keep the small message because IoT Core meters in 5 KB increments, so cost per message is the same either way. Note this deviation in the report.

**Patient codes:** `P0001`…`P{N}` with `N = SEED_PATIENTS` (default 100); device `dev-0007` maps to patient `P0007`. Schema init seeds these into `patients`. A reading whose `patient_ref` is not seeded is rejected (foreign key).

**Transport**
- HTTP: `POST /readings` → `201` stored, `200` duplicate `(device_id, seq)`, `422` invalid range or unknown patient.
- MQTT: publish to `vitals/<device_id>` at QoS 1; the worker subscribes to `vitals/#`. Invalid or duplicate messages are logged and acked, never raised out of the loop.

**Processor:** `main.py` builds one `process(reading) -> "stored" | "duplicate"` and injects it into `api.py` and the worker. Neither knows about the database.

**Generator log** (Locust and paho write the same format): CSV `device_id,seq,send_time_utc,result,rtt_ms`. `result` is `ok` (HTTP 201 / MQTT PUBACK), `duplicate` (HTTP 200), `timeout`, or `error`. `send_time_utc` and `rtt_ms` come from the generator's own clock. Each run folder `results/<date>_<stage>_<protocol>_<rate>_r<n>/` also holds `settings.json`, `ping.txt` (baseline ping, reported separately) and, from the Locust generator, `generator_summary.json` (counts, achieved rate, schedule lag). The Locust generator puts the run tag in `device_id` (`<stage>h<rate>r<n>`, for example `ah100r2-dev-0007`; `patient_ref` stays `P0007`), so lost-readings queries filter on `device_id LIKE 'ah100r2-%'`. The paho generator (`loadtest/mqtt_generator.py`, wrapper `run_mqtt.sh`) writes the same files and summary keys (plus `connections`) into `results/<date>_<stage>_mqtt_<rate>_r<n>/`; its tag is `<stage>m<rate>r<n>` (for example `am100r2-dev-0007`), and its `ok` is the **broker's** PUBACK, not proof that the worker stored the reading, so compare the generator's `ok` count with the stored row count. `loadtest/stub_mqtt_broker.py` is the PUBACK-delay stub used to calibrate it alone.

**Run modes:** `python -m app.main api` and `python -m app.main worker` (same image, two containers). Env var names are listed in `.env.example`.

## Database schema

- **patients** – `patient_ref` (primary key), `name`. Seeded with synthetic names. Patient names never appear in `readings`.
- **readings** – `id`, `device_id`, `patient_ref` (foreign key → `patients`), `heart_rate`, `spo2`, `temperature`, `seq`, `sent_at`, `abnormal`, `received_at`, `stored_at`. Unique on `(device_id, seq)`.
- `received_at` and `stored_at` both come from the app clock (never Postgres `now()`). `stored_at` is written by a second `UPDATE` after the insert commits, so it is briefly `NULL`; queries ignore `NULL`.

## Stage differences

Settings-only; no forked code. See `CLAUDE.md` §Project context for the A / B / C table.

## Compose stack (Stages A and B)

`infra/docker-compose.yml` is the same file on the laptop and on the EC2 VM. Four services: `postgres` (healthcheck, named volume), `mosquitto` (`infra/mosquitto/mosquitto.conf`: anonymous listener on 1883, persistence, queue limit raised), `api` and `worker` (one image from `infra/Dockerfile`, Python 3.12; commands `python -m app.main api` / `worker`). `api` and `worker` wait for Postgres to be healthy and get `DATABASE_URL` and `MQTT_HOST` from Compose, everything else from `.env`. Published on the host: 8000 (API), 1883 (MQTT), 5432 or `POSTGRES_HOST_PORT` (Postgres). Anonymous MQTT is for local and firewalled testing only.

## Tests

- **Unit/API** (`tests/unit`, `tests/api`): mocked, no services needed. Plain `pytest`.
- **Integration** (`tests/integration`, marker `integration`): black-box tests against a *running* stack, so the same files run on the laptop (A), the EC2 VM (B) and RDS (C, run from the VM). Set `TEST_BASE_URL`, `TEST_DATABASE_URL`, `TEST_MQTT_HOST` (and optionally `TEST_MQTT_PORT`); if any is unset they skip. Run with `pytest -m integration`. `test_http_path.py` is transport-independent; `test_mqtt_path.py` is the only file tied to the MQTT input, so Stage C adds an SQS variant of it and nothing else changes. Each test uses a unique `it-<uuid>-...` `device_id` and the run deletes its own rows afterwards. The package has an `__init__.py` so its `conftest.py` does not shadow `tests/conftest.py`.
