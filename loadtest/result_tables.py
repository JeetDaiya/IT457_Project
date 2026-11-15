"""Compact per-run stats and the result tables for docs/RESULTS.md.

    python loadtest/result_tables.py stats [results-dir=results]
        Reads the raw run folders (needs each generator_log.csv) and writes results/run_stats.csv (one line per run)
        and results/restart_stats.csv (one line per restart-test run). Stage C runs (a queue_depth.csv in the folder)
        also get a line in results/queue_stats.csv: workers, queue peak, drain time, stored per second.
        Lines of runs whose folder is not on this machine are kept, so the files can be refreshed after the raw
        folders have been archived elsewhere.

    python loadtest/result_tables.py [results-dir=results] [doc=docs/RESULTS.md]
        Rewrites every block in the doc marked like the one below from those two CSV files (no raw folders needed):

    <!-- result_tables: matrix stage=A kinds=http,mqtt-100conn -->
    ...generated, replaced on every run...
    <!-- /result_tables -->
    <!-- result_tables: restart stage=A kind=mqtt-100conn-restart -->

matrix:  one row per rate and kind; each number is the mean over the repeats, with (lowest-highest) when there are several.
restart: one row per repeat (longest gap between stored_at values, sent, stored, backlog drain).
queue:   Stage C only, <!-- result_tables: queue stage=C kinds=mqtt-100conn,mqtt-100conn-w2 -->: one row per kind and rate with the
         worker count, queue peak, seconds until the queue was empty after sending stopped, and readings stored per second.
Run folders are named <date>_<Stage>_<kind>_<rate>per-s_run<n> (loadtest/run_name.sh).
"""

import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path

NAME = re.compile(
    r"^\d{4}-\d\d-\d\d_(?P<stage>[^_]+)_(?P<kind>[^_]+)_(?P<rate>\d+)per-s_run(?P<repeat>\d+)$"
)
BLOCK = re.compile(
    r"(<!-- result_tables: (?P<type>\w+) (?P<args>[^>]*?) -->\n)(?P<body>.*?)(<!-- /result_tables -->)",
    re.DOTALL,
)
RUN_COLS = [
    "run", "stage", "kind", "rate", "repeat", "sent", "ok", "timeout", "error", "stored", "missing", "lost_formula",
    "achieved_rate", "server_avg_ms", "server_p95_ms", "rtt_min_ms", "rtt_median_ms", "rtt_p95_ms", "rtt_p99_ms",
    "rtt_max_ms", "ping_min_ms", "lag_p99_ms", "lag_max_ms", "max_in_flight",
]
RESTART_COLS = [
    "run", "stage", "kind", "rate", "repeat", "gap_s", "gap_from_utc", "gap_to_utc", "stop_requested_utc",
    "stop_returned_utc", "start_requested_utc", "start_returned_utc", "seconds_above_110pct", "peak_stored_per_s",
]


QUEUE_COLS = ["run", "workers", "queue_peak", "drain_s", "stored_per_s"]


def percentile(sorted_values: list[float], p: float) -> float:
    return sorted_values[math.ceil(p * len(sorted_values)) - 1]


def read_run(folder: Path, m: re.Match) -> dict:
    db = (folder / "db_summary.txt").read_text()
    gen = json.loads((folder / "generator_summary.json").read_text())
    server = re.search(r"avg ([\d.]+) ms, slowest 5% \(p95\) ([\d.]+) ms", db)
    with open(folder / "generator_log.csv", newline="") as f:
        rtts = sorted(float(r["rtt_ms"]) for r in csv.DictReader(f) if r["result"] == "ok" and r["rtt_ms"])
    ping = re.search(r"= ([\d.]+)/", (folder / "ping.txt").read_text())
    stored = int(re.search(r"stored rows: (\d+)", db).group(1))
    return {
        "run": folder.name, "stage": m["stage"], "kind": m["kind"], "rate": m["rate"], "repeat": m["repeat"],
        "sent": gen["started"], "ok": gen["results"]["ok"], "timeout": gen["results"]["timeout"],
        "error": gen["results"]["error"], "stored": stored, "missing": gen["started"] - stored,
        "lost_formula": int(re.search(r"distinct seq\): (-?\d+)", db).group(1)),
        "achieved_rate": gen["achieved_rate"], "server_avg_ms": server.group(1), "server_p95_ms": server.group(2),
        "rtt_min_ms": rtts[0], "rtt_median_ms": statistics.median(rtts), "rtt_p95_ms": percentile(rtts, 0.95),
        "rtt_p99_ms": percentile(rtts, 0.99), "rtt_max_ms": rtts[-1],
        "ping_min_ms": ping.group(1) if ping else "", "lag_p99_ms": gen["lag_p99_ms"],
        "lag_max_ms": gen["lag_max_ms"], "max_in_flight": gen["max_in_flight"],
    }


def read_restart(folder: Path, m: re.Match) -> dict:
    steps = dict(l.strip().split("=", 1) for l in (folder / "worker_restart.txt").read_text().splitlines() if "=" in l)
    gap = (folder / "restart_summary.txt").read_text().strip().splitlines()[-1].split(",")
    started = steps["start_returned"][11:19]
    with open(folder / "stored_per_second.csv", newline="") as f:
        burst = [int(r["stored"]) for r in csv.DictReader(f)
                 if r["second_utc"] >= started and int(r["stored"]) > 1.1 * int(m["rate"])]
    return {
        "run": folder.name, "stage": m["stage"], "kind": m["kind"], "rate": m["rate"], "repeat": m["repeat"],
        "gap_s": gap[0], "gap_from_utc": gap[1], "gap_to_utc": gap[2],
        "stop_requested_utc": steps["stop_requested"], "stop_returned_utc": steps["stop_returned"],
        "start_requested_utc": steps["start_requested"], "start_returned_utc": steps["start_returned"],
        "seconds_above_110pct": len(burst), "peak_stored_per_s": max(burst) if burst else "",
    }


def read_queue(folder: Path) -> dict:
    """Stage C extras: worker count and stored per second from db_summary.txt, peak from the 5 s queue samples."""
    db = (folder / "db_summary.txt").read_text()
    workers = re.search(r"^workers: (\d+)", db, re.MULTILINE)
    rate = re.search(r"stored per second: ([\d.]+)", db)
    drained = re.search(r"queue drained after (\d+) s", db)
    with open(folder / "queue_depth.csv", newline="") as f:
        peak = max((int(r["visible"]) for r in csv.DictReader(f)), default=0)
    return {
        "run": folder.name, "workers": workers.group(1) if workers else "", "queue_peak": peak,
        "drain_s": drained.group(1) if drained else ("not drained" if "queue did not drain" in db else ""),
        "stored_per_s": rate.group(1) if rate else "",
    }


def write_merged(path: Path, cols: list[str], rows: list[dict]) -> None:
    """Rows of runs that are not in `rows` are kept, so a refresh never drops archived runs."""
    merged = {}
    if path.exists():
        with open(path, newline="") as f:
            merged = {r["run"]: r for r in csv.DictReader(f)}
    merged.update({r["run"]: r for r in rows})
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(merged[k] for k in sorted(merged))


def write_stats(results: Path) -> tuple[int, int]:
    runs, restarts, queues = [], [], []
    for folder in sorted(results.iterdir()):
        m = NAME.match(folder.name)
        if m and (folder / "db_summary.txt").exists():
            runs.append(read_run(folder, m))
            if (folder / "restart_summary.txt").exists():
                restarts.append(read_restart(folder, m))
            if (folder / "queue_depth.csv").exists():
                queues.append(read_queue(folder))
    write_merged(results / "run_stats.csv", RUN_COLS, runs)
    write_merged(results / "restart_stats.csv", RESTART_COLS, restarts)
    if queues or (results / "queue_stats.csv").exists():
        write_merged(results / "queue_stats.csv", QUEUE_COLS, queues)
    return len(runs), len(restarts)


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def spread(values: list[float], digits: int = 2) -> str:
    mean = f"{statistics.mean(values):.{digits}f}"
    if len(values) == 1:
        return mean
    return f"{mean} ({min(values):.{digits}f}-{max(values):.{digits}f})"


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def matrix(runs: list[dict], stage: str, kinds: list[str]) -> str:
    rows = []
    for rate in sorted({int(r["rate"]) for r in runs if r["stage"] == stage}):
        for kind in kinds:
            g = [r for r in runs if (r["stage"], r["kind"], int(r["rate"])) == (stage, kind, rate)]
            if not g:
                continue
            def col(name, g=g):
                return [float(r[name]) for r in g]

            pings = [float(r["ping_min_ms"]) for r in g if r["ping_min_ms"] != ""]
            rows.append([
                str(rate), kind, str(len(g)),
                spread(col("server_avg_ms")), spread(col("server_p95_ms")),
                spread(col("rtt_median_ms"), 1), spread(col("rtt_p95_ms"), 1),
                f"{min(pings):.1f}" if pings else "n/a",
                str(sum(int(r["missing"]) for r in g)), str(sum(int(r["lost_formula"]) for r in g)),
            ])
    header = ["Rate (msg/s)", "Kind", "Runs", "Server time avg (ms)", "Server time p95 (ms)",
              "Round trip median (ms)", "Round trip p95 (ms)", "Fastest ping (ms)", "Missing (sum)", "Lost formula (sum)"]
    return table(header, rows)


def restart(runs: list[dict], restarts: list[dict], stage: str, kind: str) -> str:
    by_run = {r["run"]: r for r in runs}
    rows = []
    for r in sorted((r for r in restarts if (r["stage"], r["kind"]) == (stage, kind)), key=lambda r: int(r["repeat"])):
        run = by_run[r["run"]]
        rows.append([
            r["repeat"], r["gap_s"], run["sent"], run["stored"], run["missing"], run["lost_formula"],
            r["seconds_above_110pct"], r["peak_stored_per_s"],
        ])
    header = ["Repeat", "Longest gap between stored readings (s)", "Sent", "Stored", "Missing", "Lost formula",
              "Seconds above 110% of the rate after restart", "Peak stored per second"]
    return table(header, rows)


def queue(runs: list[dict], queues: list[dict], stage: str, kinds: list[str]) -> str:
    """Stage C: one row per kind (the worker count is part of the kind) and rate."""
    by_run = {q["run"]: q for q in queues}
    rows = []
    for kind in kinds:
        for rate in sorted({int(r["rate"]) for r in runs if (r["stage"], r["kind"]) == (stage, kind)}):
            g = [r for r in runs if (r["stage"], r["kind"], int(r["rate"])) == (stage, kind, rate) and r["run"] in by_run]
            if not g:
                continue
            q = [by_run[r["run"]] for r in g]

            def col(name, digits=0, q=q):
                values = [float(x[name]) for x in q if x[name] != ""]
                return spread(values, digits) if values else "n/a"

            drained = [x["drain_s"] for x in q]
            rows.append([
                "/".join(sorted({x["workers"] for x in q if x["workers"]})) or "n/a", str(rate), kind, str(len(g)),
                spread([float(r["server_avg_ms"]) for r in g]), spread([float(r["rtt_median_ms"]) for r in g], 1),
                spread([float(r["rtt_p95_ms"]) for r in g], 1), col("queue_peak"),
                "not drained" if "not drained" in drained else (col("drain_s") if all(drained) else "n/a"),
                col("stored_per_s", 1), str(sum(int(r["missing"]) for r in g)),
            ])
    header = ["Workers", "Rate (msg/s)", "Kind", "Runs", "Server time avg (ms)", "Round trip median (ms)", "Round trip p95 (ms)",
              "Queue peak (messages, 5 s samples)", "Queue empty after sending stopped (s)", "Stored per second", "Missing (sum)"]
    return table(header, rows)


def update(doc: Path, runs: list[dict], restarts: list[dict], queues: list[dict] | None = None) -> int:
    count = 0

    def fill(m: re.Match) -> str:
        nonlocal count
        count += 1
        args = dict(a.split("=", 1) for a in m["args"].split())
        if m["type"] == "matrix":
            body = matrix(runs, args["stage"], args["kinds"].split(","))
        elif m["type"] == "restart":
            body = restart(runs, restarts, args["stage"], args["kind"])
        elif m["type"] == "queue":
            body = queue(runs, queues or [], args["stage"], args["kinds"].split(","))
        else:
            raise SystemExit(f"unknown block type: {m['type']}")
        return m.group(1) + "\n" + body + "\n" + m.group(5)

    doc.write_text(BLOCK.sub(fill, doc.read_text()))
    return count


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "stats":
        results = Path(args[1] if len(args) > 1 else "results")
        n_runs, n_restarts = write_stats(results)
        print(f"run_stats.csv: {n_runs} runs read, restart_stats.csv: {n_restarts}")
    else:
        results = Path(args[0] if args else "results")
        doc = Path(args[1] if len(args) > 1 else "docs/RESULTS.md")
        queue_file = results / "queue_stats.csv"
        n = update(
            doc, read_csv(results / "run_stats.csv"), read_csv(results / "restart_stats.csv"),
            read_csv(queue_file) if queue_file.exists() else [],
        )
        print(f"{n} blocks updated in {doc}")
