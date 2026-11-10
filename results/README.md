# results/

Measured runs. Git holds the small, cited files; the full run folders are archived in the team Drive.

## In git
- `summary.csv`: one line per run (server time, lost readings, notes), appended by `loadtest/measure_run.sh`.
- `run_stats.csv`: one line per run with the numbers `docs/RESULTS.md` uses (sent, ok, timeouts, stored, missing, lost formula,
  server time, round trip min / median / p95 / p99 / max, fastest ping, schedule lag). `restart_stats.csv`: the same for restart-test runs.
- `<run folder>/settings.json`: how each run was configured.
- `name_map.csv`: old folder name, new folder name and database run tag of the 39 Stage A runs (folders were renamed on 2026-11-11).

## In the team Drive (archive)
- Link: **TODO: add the Drive link after the upload.**
- File: `it457-stage-a-raw-results.zip` (4.4 MB, 39 run folders, 321 entries, made 2026-11-11).
- SHA-256: `8878176c9a2467ba2cd2f68af10746b64abb2b7f40890d4fc97f7521dea62533`
- Check it with `sha256sum it457-stage-a-raw-results.zip`; restore with `unzip it457-stage-a-raw-results.zip -d results/`
  (the run folders are ignored by git except `settings.json`).
- Add a new zip (and its checksum here) for each later stage.

## What is in a run folder
`generator_log.csv` (one line per message: device, `seq`, send time, result, round trip; the only file the round-trip numbers come from),
`generator_summary.json` (generator totals, schedule lag), `db_summary.txt` (stored rows, server time, lost readings),
`ping.txt` (baseline ping), `network_check.txt` (router, Wi-Fi and Tailscale check before the run; the Oracle address is replaced
with `<oracle-ip>`), `laptop_vmstat.txt` (laptop CPU every 5 s), `settings.json`. Restart runs add `worker_restart.txt`,
`restart_summary.txt` and `stored_per_second.csv`. In `restart_summary.txt` and `db_summary.txt` the "run:" line shows the folder's
original name; `name_map.csv` gives the current one.

## Refresh after new runs
```bash
python loadtest/result_tables.py stats results            # raw run folders -> run_stats.csv, restart_stats.csv
python loadtest/result_tables.py results docs/RESULTS.md   # those files -> tables in docs/RESULTS.md
```
Folder naming: `<date>_<Stage>_<kind>_<rate>per-s_run<n>` (the date is UTC). Never edit or overwrite raw run files.
