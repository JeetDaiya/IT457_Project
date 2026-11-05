# Changelog

- **2026-11-04** — Scaffolded project: created folder structure (`app/`, `infra/`, `loadtest/`, `results/`), `requirements.txt`, `.env.example`, `.gitignore`, and initial docs.
- **2026-11-05** — Defined the teammate contract (layers, reading JSON, patient codes, transport, generator log format, run modes) in `ARCHITECTURE.md`, and added limit/seed settings to `.env.example`.
- **2026-11-05** — Built the Stage A app core (`service.py`, `db.py`, `api.py`, `main.py`) with an independently written suite of 172 unit/API tests; integration tests parked until Compose exists.
- **2026-11-05** — Added the MQTT worker input (`app/mqtt_in.py`: QoS 1, persistent session, reconnect, bad messages logged and skipped) with 49 unit tests, and `docs/REPORT_NOTES.md`.
- **2026-11-05** — Added the Stage A/B Docker Compose stack in `infra/` (postgres, mosquitto, api, worker); HTTP and MQTT readings checked end to end by hand.
