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
HTTP (FastAPI)  ─┐
                 ├─► process_reading()  ─► PostgreSQL
MQTT (paho)    ─┘
```

`process_reading()` is the single shared function called by both the HTTP endpoint and the MQTT subscriber. Stage C adds an SQS queue between IoT Core and the MQTT worker; only the input module changes.

## Database schema

- **readings** – `id`, `device_id`, `patient_ref`, `heart_rate`, `spo2`, `temperature`, `seq`, `sent_at`, `abnormal`, `received_at`, `stored_at`. Unique on `(device_id, seq)`.
- **patients** – patient reference to name mapping. Patient names never appear in `readings`.

## Stage differences

Settings-only; no forked code. See `CLAUDE.md` §Project context for the A / B / C table.
