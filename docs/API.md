# API

The Mini HealthSuite service has a small HTTP API (FastAPI, port 8000) and one MQTT input. Both use the same reading format and the same function, `process_reading()`, so only the way the data travels differs. Source: `app/api.py` (routes) and `app/rules.py` (reading format and limits).

FastAPI also serves its own interactive docs at `/docs` (Swagger) and the machine-readable schema at `/openapi.json`.

**Base URL:** `http://<host>:8000`, for example `http://localhost:8000` on Stage A or `http://<ec2-ip>:8000` on Stages B and C.

## Endpoints

| Method | Path | Purpose | Success |
|---|---|---|---|
| `POST` | `/readings` | Send one reading | `201` stored, `200` duplicate |
| `GET` | `/readings/latest` | Newest readings, newest first | `200` |
| `GET` | `/stats` | Counters | `200` |
| `GET` | `/health` | Is the database reachable | `200` (`503` if not) |
| `GET` | `/` | Web form to send one reading | `200` (HTML) |
| `GET` | `/dashboard/` | Results dashboard (static page that reads the endpoints above) | `200` (HTML) |

### POST /readings

Send one reading as JSON (about 0.5 KB).

| Field | Type | Rule |
|---|---|---|
| `device_id` | string | not empty |
| `patient_ref` | string | not empty; a code such as `P0007`, never a name; must exist in the `patients` table |
| `heart_rate` | integer | 20 to 250 |
| `spo2` | integer | 50 to 100 |
| `temperature` | number | 30 to 45 (degrees C) |
| `seq` | integer | 1 or more; counter per device |
| `sent_at` | string | ISO 8601 time with a time zone, for example `2026-11-16T09:30:00Z` |

```bash
curl -X POST http://localhost:8000/readings \
  -H "Content-Type: application/json" \
  -d '{"device_id":"dev-0001","patient_ref":"P0001","heart_rate":72,"spo2":97,
       "temperature":36.8,"seq":1,"sent_at":"2026-11-16T09:30:00Z"}'
```

Responses:

| Status | Body | Meaning |
|---|---|---|
| `201` | `{"outcome":"stored"}` | The reading was saved. |
| `200` | `{"outcome":"duplicate"}` | This `(device_id, seq)` was already stored. It is ignored, not an error, because a message can be delivered twice. |
| `422` | error details | A value is outside its range, a field is missing or has the wrong type, or `patient_ref` is unknown (`unknown patient_ref: ...`). |

The service sets `abnormal` itself: it is true when a valid value is outside the normal limits (see below). The client does not send it.

### GET /readings/latest

Returns a JSON list of the newest readings, newest first.

| Query parameter | Default | Allowed |
|---|---|---|
| `limit` | 50 | 1 to 500 (otherwise `422`) |

```bash
curl "http://localhost:8000/readings/latest?limit=5"
```

Each item has: `id`, `device_id`, `patient_ref`, `heart_rate`, `spo2`, `temperature`, `seq`, `sent_at`, `abnormal`, `received_at` (when the app first saw the reading) and `stored_at` (after the insert committed). Patient names are never returned.

### GET /stats

```bash
curl http://localhost:8000/stats
```

```json
{"total": 1200, "abnormal": 37, "devices": 100, "latest_received_at": "2026-11-16T09:30:01.234567Z"}
```

`total` is all stored readings, `abnormal` those flagged abnormal, `devices` the number of distinct devices, and `latest_received_at` the newest `received_at`.

### GET /health

Runs a trivial query against the database. Used to check that the stack is up.

| Status | Body |
|---|---|
| `200` | `{"status":"ok"}` |
| `503` | `{"status":"unavailable"}` (database not reachable) |

## MQTT input

Instead of calling `POST /readings`, a device can publish the same JSON to the broker.

| Stage | Broker | Topic the devices publish to | How it reaches the worker |
|---|---|---|---|
| A, B | Mosquitto, port 1883 (plain) | `vitals/<device_id>` | The worker subscribes to `vitals/#` (QoS 1) |
| C | AWS IoT Core, port 8883 (TLS, device certificate) | `mini-hs/vitals/<device_id>` | IoT rule `SELECT * FROM 'mini-hs/vitals/+'` sends each message to an SQS queue; the worker long-polls the queue |

Details that differ from HTTP:

- There is no reply to the device. An invalid reading or an unknown `patient_ref` is logged by the worker and dropped; it does not stop the worker.
- A duplicate `(device_id, seq)` is ignored, as with HTTP, because QoS 1 can deliver a message twice.
- In Stage C a queue message is deleted only after the reading is stored, a duplicate or rejected as invalid. Other errors leave it in the queue to be retried.
- The input is chosen by the `INPUT_MODE` setting (`mqtt` or `sqs`).

## Rules and limits

**Rejected (422 over HTTP):** heart rate outside 20 to 250, SpO2 outside 50 to 100, temperature outside 30 to 45.

**Abnormal flag.** A valid reading is marked abnormal when any value is outside the normal limits. The limits are settings with these defaults (assumptions, not clinical advice):

| Setting | Default | Abnormal when |
|---|---|---|
| `HEART_RATE_MIN` / `HEART_RATE_MAX` | 50 / 120 | heart rate outside the range |
| `SPO2_MIN` | 92 | SpO2 below the value |
| `TEMPERATURE_MIN` / `TEMPERATURE_MAX` | 35.5 / 38.0 | temperature outside the range |

**Patients.** The `patients` table is seeded with synthetic codes `P0001` to `P0100` (`SEED_PATIENTS`, default 100). All data is synthetic.

## Settings that affect the API

Read from environment variables (`app/settings.py`, example in `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | none, required | PostgreSQL connection URL |
| `INPUT_MODE` | `mqtt` | Worker input: `mqtt` or `sqs` |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC` | `localhost`, `1883`, `vitals/#` | Broker the worker subscribes to (`INPUT_MODE=mqtt`) |
| `SQS_QUEUE_URL` | none | Queue the worker reads; required when `INPUT_MODE=sqs` |
| `SEED_PATIENTS` | 100 | Number of synthetic patients created |
| `LOG_LEVEL` | `INFO` | Log level |
