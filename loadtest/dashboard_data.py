"""Results data for the dashboard page, built from the compact stats files.

    python -m loadtest.dashboard_data [results-dir=results] [out=app/static/dashboard/results.json]

Reads results/run_stats.csv, results/restart_stats.csv and (if present) results/queue_stats.csv, written by
result_tables.py, and writes one JSON file the dashboard charts read. Like the RESULTS.md tables, each number
is the mean over the repeats, except sent, stored and missing, which are sums. The one-off "check" runs are left
out, as in RESULTS.md. Re-run it after result_tables.py whenever new runs are added.
"""

import json
import statistics
import sys
from pathlib import Path

from loadtest.result_tables import read_csv

MEAN_COLS = [
    "server_avg_ms",
    "server_p95_ms",
    "rtt_median_ms",
    "rtt_p95_ms",
    "ping_min_ms",
]
SUM_COLS = ["sent", "stored", "missing"]
QUEUE_MEAN_COLS = ["queue_peak", "drain_s", "stored_per_s"]


def measured(runs: list[dict]) -> list[dict]:
    """Drop the short trial runs (kind contains "-check"), which RESULTS.md also leaves out."""
    return [r for r in runs if "-check" not in r["kind"]]


def mean(values: list[str], digits: int = 2) -> float:
    return round(statistics.mean(float(v) for v in values), digits)


def matrix(runs: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in measured(runs):
        groups.setdefault((r["stage"], r["kind"], int(r["rate"])), []).append(r)
    rows = []
    for (stage, kind, rate), group in sorted(groups.items()):
        row = {"stage": stage, "kind": kind, "rate": rate, "runs": len(group)}
        for col in SUM_COLS:
            row[col] = sum(int(r[col]) for r in group)
        for col in MEAN_COLS:
            row[col] = mean([r[col] for r in group])
        row["stored_pct"] = round(100 * row["stored"] / row["sent"], 1)
        rows.append(row)
    return rows


def restarts(rows: list[dict]) -> list[dict]:
    # peak_stored_per_s is empty when the catch-up never went above 110% of the rate (Stage C).
    return [
        {
            "stage": r["stage"],
            "repeat": int(r["repeat"]),
            "gap_s": float(r["gap_s"]),
            "seconds_above_110pct": int(r["seconds_above_110pct"]),
            "peak_stored_per_s": int(r["peak_stored_per_s"])
            if r["peak_stored_per_s"]
            else None,
        }
        for r in rows
    ]


def queues(rows: list[dict], runs: list[dict]) -> list[dict]:
    """Queue peak, drain time and stored per second per setting (Stage C), means over the repeats."""
    by_run = {r["run"]: r for r in measured(runs)}
    groups: dict[tuple, list[dict]] = {}
    for q in rows:
        r = by_run.get(q["run"])
        if r is None or not q["workers"] or not q["stored_per_s"]:
            continue
        key = (r["stage"], r["kind"], int(r["rate"]), int(q["workers"]))
        groups.setdefault(key, []).append(q)
    return [
        {"stage": stage, "kind": kind, "rate": rate, "workers": workers}
        | {"runs": len(group)}
        | {col: mean([q[col] for q in group], 1) for col in QUEUE_MEAN_COLS}
        for (stage, kind, rate, workers), group in sorted(groups.items())
    ]


def build(results: Path) -> dict:
    runs = read_csv(results / "run_stats.csv")
    queue_file = results / "queue_stats.csv"
    return {
        "source": "results/run_stats.csv, restart_stats.csv and queue_stats.csv",
        "matrix": matrix(runs),
        "restart": restarts(read_csv(results / "restart_stats.csv")),
        "queue": queues(read_csv(queue_file), runs) if queue_file.exists() else [],
    }


def main(argv: list[str]) -> int:
    results = Path(argv[0]) if argv else Path("results")
    out = Path(argv[1]) if len(argv) > 1 else Path("app/static/dashboard/results.json")
    data = build(results)
    out.write_text(json.dumps(data, indent=1) + "\n")
    print(
        f"{out}: {len(data['matrix'])} matrix rows, {len(data['restart'])} restart rows,"
        f" {len(data['queue'])} queue rows"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
