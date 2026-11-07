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
- **The MQTT worker uses a persistent session** (fixed client ID `healthsuite-worker`, `clean_session=False`), so Mosquitto queues QoS 1 messages while it is down (checked: 5 messages sent while the worker was stopped were all stored after restart). Run only **one** worker per client ID; a second one with the same ID kicks the first off.
- **paho-mqtt 1.6.1 allows only 20 in-flight QoS 1 messages by default** (checked on the client object). At a 200–250 ms round trip that caps one connection at roughly 80–100 msg/s; the generator must call `max_inflight_messages_set()` and probably use several connections.
- **An error inside `process` (for example the database being down) is logged and the message is still acked, so that reading is lost.** Only the worker's loop is protected, not the reading. Count this as lost readings in any outage test.
- **Laptop Python is 3.14; containers use 3.12.** Some packages may lack 3.14 builds, so run tests in a 3.12 venv.
- **Stage C server time excludes the SQS wait.** `received_at` is stamped by the worker, after the queue.
- **Database URLs must say `postgresql+psycopg2://`.** A bare `postgresql://` makes SQLAlchemy 2.1 look for psycopg v3 and the app crashes with `No module named 'psycopg'` (checked with SQLAlchemy 2.1.8, which `requirements.txt` resolves to). Compose already builds the right URL; the `DATABASE_URL` in `.env.example` is still the bare form.
- **Run Compose from the repo root with `--env-file .env`** (`docker compose --env-file .env -f infra/docker-compose.yml up --build`), otherwise `${POSTGRES_*}` is read from `infra/` and Compose fails with "set POSTGRES_… in .env".
- **A local PostgreSQL on the laptop usually already owns port 5432.** Set `POSTGRES_HOST_PORT` (for example 5433) in `.env`; containers still talk to each other on 5432.
- **Mosquitto queues at most 1000 messages per client by default** (its documented default, not measured here). `infra/mosquitto/mosquitto.conf` raises it to 100000, because the 20 s restart test at 100 msg/s queues about 2000.

- **Locust's `FastHttpUser` allows only 10 concurrent connections by default** (`concurrency`, read from its source). At a 200-250 ms round trip that would silently turn the open-loop generator into a closed loop at about 40-50 msg/s; `loadtest/locustfile.py` sets the pool to 2 x rate.
- **paho-mqtt calls `on_publish` while holding its own lock** (read from the 1.6.1 source), so calling `publish()` while holding a lock that `on_publish` also needs deadlocks. `loadtest/mqtt_generator.py` registers a message only after `publish()` returns and keeps a PUBACK that arrives before that.
- **paho-mqtt 1.6.1 keeps a QoS 1 message published while disconnected** (`publish()` returns `MQTT_ERR_NO_CONN` but the message stays queued) and sends it after the reconnect; the generator logs it as `error` and ignores the late PUBACK. Packet ids wrap at 65535 per connection, so pending messages are keyed by (connection, id).
- **The MQTT generator's `ok` is the broker's PUBACK, not "the database stored it".** It covers only generator to broker; the worker acks to the broker separately after the insert. Check stored row counts against `ok` after every run.
