# Effort Log

| Date | Step | Task | Who | Start | End | Hands-on min | Manual steps | What went wrong |
|------|------|------|-----|-------|-----|-------------|-------------|----------------|
| 2026-11-04 | A build | Project scaffolding: folders, requirements.txt, docs, .env.example, .gitignore | Jeet | 22:57 | 23:01 | — | 0 | — |
| 2026-11-04 | A build | Design and team split; contract in ARCHITECTURE.md; app core (service, db, api, main); independent test suite (172 unit/API tests passing); ruff clean | Jeet | 23:30 | 00:48 (11-05) | 78 | 0 | Rules/settings were first written by the agent against the plan, then removed and inlined into service.py/main.py; integration tests parked until Teammate-II's Compose exists |
| 2026-11-04 | A build | MQTT worker input (app/mqtt_in.py) | Kavya | 01:10 | 02:05 | 55 | — | — |
| 2026-11-05 | A build | Docker Compose stack: Dockerfile, docker-compose.yml, mosquitto.conf (same file for Stages A and B) | Kavya | 13:20 | 14:00 | 40 | — | Bare `postgresql://` URL crashed the app (SQLAlchemy 2.1 looks for psycopg v3), fixed with `postgresql+psycopg2://` in Compose; local PostgreSQL already used port 5432, added `POSTGRES_HOST_PORT` |
