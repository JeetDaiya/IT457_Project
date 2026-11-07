# Changelog

- **2026-11-04** — Scaffolded project: created folder structure (`app/`, `infra/`, `loadtest/`, `results/`), `requirements.txt`, `.env.example`, `.gitignore`, and initial docs.
- **2026-11-05** — Defined the teammate contract (layers, reading JSON, patient codes, transport, generator log format, run modes) in `ARCHITECTURE.md`, and added limit/seed settings to `.env.example`.
- **2026-11-05** — Built the Stage A app core (`service.py`, `db.py`, `api.py`, `main.py`) with an independently written suite of 172 unit/API tests; integration tests parked until Compose exists.
- **2026-11-05** — Added the MQTT worker input (`app/mqtt_in.py`: QoS 1, persistent session, reconnect, bad messages logged and skipped) with 49 unit tests, and `docs/REPORT_NOTES.md`.
- **2026-11-05** — Added the Stage A/B Docker Compose stack in `infra/` (postgres, mosquitto, api, worker); HTTP and MQTT readings checked end to end by hand.
- **2026-11-05** — Extracted `Reading`, `Limits` and `is_abnormal` into `app/rules.py` and `Settings`/`load_settings` into `app/settings.py` (pure refactor, 221 tests still pass, ruff clean); updated `ARCHITECTURE.md`.
- **2026-11-07** — Added the Locust HTTP load generator in `loadtest/` (open-loop fixed schedule, run tag in `device_id`, shared CSV log plus per-run summary, calibration stub, `run_http.sh` wrapper) with tests; smoke-tested locally against the stub, calibration on the Oracle VM still to do.
- **2026-11-07** — Added the paho-mqtt load generator (`loadtest/mqtt_generator.py`, `run_mqtt.sh`: open-loop fixed schedule, QoS 1, `--connections` option, same log and summary format as Locust) and a PUBACK-delay stub broker (`stub_mqtt_broker.py`) for calibration, with 46 tests; checked on Stage A at 10 and 50 msg/s (900 readings, all stored, 0 lost); calibration on the Oracle VM still to do.
