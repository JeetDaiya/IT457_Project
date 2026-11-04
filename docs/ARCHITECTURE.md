# Architecture

## Folder layout

```
app/          – FastAPI service (settings, db, rules, api, mqtt_in, main)
infra/        – Docker Compose files, AWS scripts/notes
loadtest/     – Locust and paho-mqtt generator scripts
results/      – Raw run data, one folder per run, summary.csv
docs/         – Living docs (this file, GOTCHAS, CHANGELOG, etc.)
```

## Layers

```
HTTP (api.py)    ─┐
                  ├─► process_reading() (service.py) ─► ReadingStore port ◄─ PostgresReadingStore (db.py)
MQTT (mqtt_in.py)─┘
```

Dependencies point inward only: `api` / `mqtt_in` → `service` → `rules`. `db` implements a port that `service` defines. Only `main.py` knows all the pieces and wires them together.

| Layer | File | Responsibility |
|---|---|---|
| Application | `app/service.py` | `process_reading()` plus the ports it needs: `ReadingStore`, `Clock` |
| Infrastructure | `app/db.py` | `PostgresReadingStore` (SQLAlchemy Core + psycopg2), schema init, patient seeding, `SystemClock` |
| Interface | `app/api.py` | Thin FastAPI routers: call the injected processor, map outcome → HTTP status |
| Interface | `app/mqtt_in.py` | Parse message, call the injected processor, ack |
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

**Generator log** (Locust and paho write the same format): CSV `device_id,seq,send_time_utc,result,rtt_ms`. `result` is `ok` (HTTP 201 / MQTT PUBACK), `duplicate` (HTTP 200), `timeout`, or `error`. `send_time_utc` and `rtt_ms` come from the generator's own clock.

**Run modes:** `python -m app.main api` and `python -m app.main worker` (same image, two containers). Env var names are listed in `.env.example`.

## Database schema

- **patients** – `patient_ref` (primary key), `name`. Seeded with synthetic names. Patient names never appear in `readings`.
- **readings** – `id`, `device_id`, `patient_ref` (foreign key → `patients`), `heart_rate`, `spo2`, `temperature`, `seq`, `sent_at`, `abnormal`, `received_at`, `stored_at`. Unique on `(device_id, seq)`.
- `received_at` and `stored_at` both come from the app clock (never Postgres `now()`). `stored_at` is written by a second `UPDATE` after the insert commits, so it is briefly `NULL`; queries ignore `NULL`.

## Stage differences

Settings-only; no forked code. See `CLAUDE.md` §Project context for the A / B / C table.
