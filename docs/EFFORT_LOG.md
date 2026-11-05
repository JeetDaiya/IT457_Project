# Effort Log

| Date | Step | Task | Who | Start | End | Hands-on min | Manual steps | What went wrong |
|------|------|------|-----|-------|-----|-------------|-------------|----------------|
| 2026-11-04 | A build | Project scaffolding: folders, requirements.txt, docs, .env.example, .gitignore | Jeet | 22:57 | 23:01 | — | 0 | — |
| 2026-11-04 | A build | Design and team split; contract in ARCHITECTURE.md; app core (service, db, api, main); independent test suite (172 unit/API tests passing); ruff clean | Jeet | 23:30 | 00:48 (11-05) | 78 | 0 | Rules/settings were first written by the agent against the plan, then removed and inlined into service.py/main.py; integration tests parked until Teammate-II's Compose exists |
| 2026-11-05 | A build | Extract rules.py and settings.py out of service.py and main.py (pure refactor; importers and tests updated) | Bhavya | 14:15 | 14:45 | 30 | 0 | Python 3.12 not in apt on Ubuntu 26.04, so used uv; brief said 172 tests but baseline is 221; brief's ARCHITECTURE rows did not exist so added new ones; mqtt_in.py (Teammate-II) needed two import-line edits |
