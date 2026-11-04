This project is for IT457 Cloud Computing: a 5-week team case study on Philips HealthSuite Digital Platform (Migration & Transformation theme).

## Where to look

| Need to... | Read |
|---|---|
| Understand layers, interfaces/adapters, DB schema, current folder layout | `docs/ARCHITECTURE.md` |
| Avoid re-breaking something that's broken before | `docs/GOTCHAS.md`|
| Know what's deployed where, CI/CD, env vars | `docs/DEPLOYMENT.md` |
| See why something is built the way it is / project history | `docs/CHANGELOG.md` |
| Check planned-but-not-built features (don't build unless asked) | `docs/ROADMAP.md` |

## Working style
*(Applies to every task. Trivial one-liners don't need the full ceremony — use judgment.)*
## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Repo-specific rules
- **Feature branches** — always create a feature branch (e.g. `feature/<short-name>`) before
  starting work. Never commit directly to `main`. Merge via pull request after review.
- **No commits without approval** — never run `git commit` or `git push` unless the user
  explicitly approves. Present the changes and ask first.
- `ARCHITECTURE.md` and `GOTCHAS.md` are **living references** — edit them in place when the
  thing they describe changes. Never append a dated entry to them.
- `CHANGELOG.md` is an **append-only log** — add one short dated bullet when you finish
  something. Never put prose explanations there; that belongs in a commit message or PR.
- If you change something `ARCHITECTURE.md` or `GOTCHAS.md` describes, update that file in the
  same piece of work — don't leave it for later.

## Project context: "Mini HealthSuite"
Simulated medical devices send vital signs to the cloud. The same app is built in three stages that mirror Philips' two migration phases:

| Stage | Where it runs | Database | MQTT broker | Readings reach the workers |
|---|---|---|---|---|
| A | Laptop, Docker Compose | PostgreSQL in Docker | Mosquitto in Docker | Straight from the broker |
| B | One EC2 VM (us-east-1), same Compose file | PostgreSQL on the VM | Mosquitto on the VM | Straight from the broker |
| C | EC2 plus managed services | Amazon RDS (single-AZ, for budget) | AWS IoT Core | IoT rule → SQS queue → workers |

- A → B is lift-and-shift: nothing changes except where it runs. B → C is refactoring: only settings and one input module (reads the queue) change. Keep it that way; stage differences live in settings, not in forked code.
- Stack: Python, FastAPI, PostgreSQL, paho-mqtt, Docker Compose. AWS region is `us-east-1` because the report's cost model is priced there.
- Load generator: an Oracle Cloud Always Free ARM instance (2 cores) in Mumbai, **outside AWS**. Locust for HTTP, a paho-mqtt script for MQTT. It must never run on a machine that is being migrated.
- Folders: `app/` (service), `infra/` (Compose files, AWS notes/scripts), `loadtest/` (generator scripts, settings), `results/` (raw runs), `docs/`.
- The LaTeX report is separate. Do not edit report text from here unless asked.

## Scope (don't build unless asked)
- Required: Stages A, B, C; the HTTP vs MQTT comparison; the queue; the B → C migration test; the measurements below.
- Planned but optional: small dashboard (latest readings with abnormal highlighted, one chart, counters; timebox about two days and cut first), S3 large-file upload, IAM role instead of stored keys, Parameter Store for the DB password, CloudTrail, name-free S3 archive.
- Report-only (never build): failure/recovery design, data residency design.
- No real patient data, ever. Synthetic readings only.

## Reading spec (source of truth for app, generator and tests)
- JSON, about 0.5 KB: `device_id`, `patient_ref` (a code, never a name), `heart_rate`, `spo2`, `temperature`, `seq` (counter per device), `sent_at` (ISO 8601 UTC).
- Table `readings`: the fields above plus `id`, `abnormal`, `received_at` (when the app first saw the reading) and `stored_at` (after the insert commits). `UNIQUE (device_id, seq)`. Patient names live only in a separate `patients` table, never in `readings` or any archive.
- Reject with HTTP 422 if heart rate is outside 20–250, SpO2 outside 50–100, or temperature outside 30–45 °C.
- `abnormal` = true when a valid value is outside the normal limits kept in settings. Placeholder defaults (assumptions, say so in the report): heart rate 50–120, SpO2 ≥ 92, temperature 35.5–38.0.
- A duplicate `(device_id, seq)` is ignored and returns 200, not an error (MQTT QoS 1 can redeliver).
- One function, `process_reading()`, is called by both HTTP and MQTT, so the two differ only in how data travels.
- Endpoints: `POST /readings` (201), `GET /readings/latest?limit=50`, `GET /stats`, `GET /health`, `GET /` (web form for one reading). MQTT: subscribe to `vitals/#`.
- Files in `app/`: `settings.py`, `db.py`, `rules.py`, `api.py`, `mqtt_in.py`, `main.py`. Settings: DB URL, MQTT host/port/topic, normal limits, log level.

## Measurement rules (keep results defensible)
- **Delay is two numbers, never one.** Server time = `stored_at − received_at` (one machine, one clock). Client round trip = generator's own clock, send to acknowledgement. Record the baseline `ping` time from Oracle to the endpoint and report it separately. Never subtract timestamps from two different machines.
- **Downtime** = longest gap between consecutive `stored_at` values around the cutover, under steady load of 100 messages/second. **Lost readings** per device = `(max(seq) − min(seq) + 1) − count(distinct seq)`.
- **Settings for every run:** 0.5 KB messages; steps of 10, 50, 100 and 500 messages/second; 2 minutes per step; at most 100,000 messages per run; 3 repeats. Report average delay and the slowest 5%. Restart test: stop the worker for 20 seconds at 100 messages/second and count lost readings.
- **Generator rules:** send on a fixed clock schedule (next send = start + n × interval), never sleep-after-send; never let an error stop the loop (try/except, 2-second timeout); MQTT QoS 1; HTTP and MQTT both need many requests in flight because of the roughly 200–250 ms Mumbai → us-east-1 round trip; write its own log (device, `seq`, send time, result). Calibrate its maximum real rate before any measured run, and say so if 500/s is not reachable.
- **Migration test (B → C):** seed about 1 million rows, keep steady load running, `pg_dump` → `pg_restore` into RDS, switch the database URL, then check row counts, no `seq` gaps, sample rows identical. Log the data size and copy time.
- **Cost:** Stage B = EC2 hourly price × hours run. Stage C = IoT Core + SQS + RDS charge in the test window ÷ millions of messages. Compare the AWS bill (before credits) with usage × list price. Present the bill as a check against the calculator, not as an independent finding.

## Cost and AWS safety
- Ask before creating any paid AWS resource, and before starting any load test (confirm stage, protocol, rate and duration first).
- Stop the EC2 VM at the end of every session. Do not leave RDS, IoT Core or SQS resources running overnight unless asked. Tear everything down when measurements finish.
- Never commit secrets, `.env`, device certificates or private keys. Provide `.env.example` and keep real values out of git.
- Never run destructive commands (drop database, delete buckets or snapshots, terminate resources) without explicit confirmation.

## Logs Claude must maintain (do this without being reminded)
1. **`docs/CHANGELOG.md`** — one short dated bullet when something is finished (see Repo-specific rules).
2. **`docs/EFFORT_LOG.md`** — append one row per hands-on task, columns: `Date | Step (A build, A→B, B→C, measurement) | Task | Who | Start | End | Hands-on min | Manual steps | What went wrong`. Fill "manual steps" (number of actions someone had to do) and "what went wrong" from the session. **Never invent times.** If start, end or hands-on minutes are unknown, ask the user before writing the row. This log is the evidence for migration effort in the report.
3. **`results/`** — one folder per measured run, `results/<date>_<stage>_<protocol>_<rate>_r<n>/`, holding the settings used, the raw generator log and the query outputs. Never edit or overwrite raw results. Append one line per run to `results/summary.csv`.
4. **`docs/ARCHITECTURE.md` and `docs/GOTCHAS.md`** — update in place whenever what they describe changes. If a doc does not exist yet, create it when first needed, kept short.
5. **`docs/DEPLOYMENT.md`** — keep a "currently running AWS resources" line up to date, so nobody forgets something that costs money.
6. **Stage tags** — when a stage works, remind the user to tag the repo `stage-a`, `stage-b` or `stage-c`. Code change per stage is then `git diff --stat stage-a stage-b`.
7. **End of every work session:** before finishing, confirm that CHANGELOG and EFFORT_LOG are updated, and list any AWS resources still running.
