# Gotchas

_Things that have bitten us or are easy to get wrong. Updated in place._

- **Never subtract timestamps from two different machines.** Server delay = `stored_at − received_at`. Client round-trip = generator's own clock. Report baseline `ping` separately.
- **Never commit `.env`, certs, or private keys.** Use `.env.example` as the template.
- **Duplicate `(device_id, seq)` is not an error** — return 200, not 4xx (MQTT QoS 1 can redeliver).
- **AWS region is always `us-east-1`** — cost model is priced there.
- **`received_at` and `stored_at` both come from the app clock, never Postgres `now()`.** At Stage C the DB is on RDS, a different machine.
- **`stored_at` is briefly `NULL`.** It is set by a second `UPDATE` after the insert commits. Downtime and delay queries must ignore `NULL`.
- **Seed `patients` before any reading.** `readings.patient_ref` is a foreign key; an unseeded code is rejected (HTTP 422).
- **B→C: restore first, then start the app.** If the app starts against an empty RDS it creates the tables, and `pg_restore` then clashes with them.
- **`paho-mqtt` is pinned `<2`** (v1.x callback API). Write MQTT code in that style.
- **Laptop Python is 3.14; containers use 3.12.** Some packages may lack 3.14 builds, so run tests in a 3.12 venv.
- **Stage C server time excludes the SQS wait.** `received_at` is stamped by the worker, after the queue.
