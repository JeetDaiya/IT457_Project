"""Markdown result tables built from the raw run folders (files are only read; nothing is re-run).

    python loadtest/result_tables.py [results-dir=results] [doc=docs/RESULTS.md]

Rewrites every block in the doc that is marked like this (the text between the two markers is replaced):

    <!-- result_tables: matrix stage=A kinds=http,mqtt-100conn -->
    ...
    <!-- /result_tables -->
    <!-- result_tables: restart stage=A kind=mqtt-100conn-restart -->

matrix:  one row per rate and kind; each number is the mean over the repeats, with (lowest-highest) when there are several.
restart: one row per repeat (longest gap between stored_at values, sent, stored, backlog drain).
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
    r"^\d{4}-\d\d-\d\d_(?P<stage>[^_]+)_(?P<kind>[^_]+)_(?P<rate>\d+)per-s_run(?P<run>\d+)$"
)
BLOCK = re.compile(
    r"(<!-- result_tables: (?P<type>\w+) (?P<args>[^>]*?) -->\n)(?P<body>.*?)(<!-- /result_tables -->)",
    re.DOTALL,
)


def load_run(folder: Path, m: re.Match) -> dict:
    db = (folder / "db_summary.txt").read_text()
    summary = json.loads((folder / "generator_summary.json").read_text())
    server = re.search(r"avg ([\d.]+) ms, slowest 5% \(p95\) ([\d.]+) ms", db)
    with open(folder / "generator_log.csv", newline="") as f:
        rtts = sorted(float(r["rtt_ms"]) for r in csv.DictReader(f) if r["result"] == "ok" and r["rtt_ms"])
    ping = re.search(r"= ([\d.]+)/", (folder / "ping.txt").read_text())
    stored = int(re.search(r"stored rows: (\d+)", db).group(1))
    return {
        "folder": folder,
        "stage": m["stage"], "kind": m["kind"], "rate": int(m["rate"]), "run": int(m["run"]),
        "server_avg": float(server.group(1)), "server_p95": float(server.group(2)),
        "rtt_median": statistics.median(rtts),
        "rtt_p95": rtts[math.ceil(0.95 * len(rtts)) - 1],
        "ping_min": float(ping.group(1)) if ping else None,
        "sent": summary["started"], "stored": stored, "missing": summary["started"] - stored,
        "lost": int(re.search(r"distinct seq\): (-?\d+)", db).group(1)),
    }


def load_all(results: Path) -> list[dict]:
    runs = []
    for folder in sorted(results.iterdir()):
        m = NAME.match(folder.name)
        if m and (folder / "db_summary.txt").exists():
            runs.append(load_run(folder, m))
    return runs


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
    for rate in sorted({r["rate"] for r in runs if r["stage"] == stage}):
        for kind in kinds:
            g = [r for r in runs if (r["stage"], r["kind"], r["rate"]) == (stage, kind, rate)]
            if not g:
                continue
            pings = [r["ping_min"] for r in g if r["ping_min"] is not None]
            rows.append([
                str(rate), kind, str(len(g)),
                spread([r["server_avg"] for r in g]), spread([r["server_p95"] for r in g]),
                spread([r["rtt_median"] for r in g], 1), spread([r["rtt_p95"] for r in g], 1),
                f"{min(pings):.1f}" if pings else "n/a",
                str(sum(r["missing"] for r in g)), str(sum(r["lost"] for r in g)),
            ])
    header = ["Rate (msg/s)", "Kind", "Runs", "Server time avg (ms)", "Server time p95 (ms)",
              "Round trip median (ms)", "Round trip p95 (ms)", "Fastest ping (ms)", "Missing (sum)", "Lost formula (sum)"]
    return table(header, rows)


def restart(runs: list[dict], stage: str, kind: str) -> str:
    rows = []
    for r in sorted((r for r in runs if (r["stage"], r["kind"]) == (stage, kind)), key=lambda r: r["run"]):
        d = r["folder"]
        gap = (d / "restart_summary.txt").read_text().strip().splitlines()[-1].split(",")[0]
        started = re.search(r"start_returned=\S+T(\d\d:\d\d:\d\d)", (d / "worker_restart.txt").read_text()).group(1)
        with open(d / "stored_per_second.csv", newline="") as f:
            per_sec = [(row["second_utc"], int(row["stored"])) for row in csv.DictReader(f)]
        burst = [n for t, n in per_sec if t >= started and n > 1.1 * r["rate"]]
        rows.append([
            str(r["run"]), gap, str(r["sent"]), str(r["stored"]), str(r["missing"]), str(r["lost"]),
            str(len(burst)), str(max(burst)) if burst else "-",
        ])
    header = ["Repeat", "Longest gap between stored readings (s)", "Sent", "Stored", "Missing", "Lost formula",
              "Seconds above 110% of the rate after restart", "Peak stored per second"]
    return table(header, rows)


def render(runs: list[dict], kind: str, args: dict[str, str]) -> str:
    if kind == "matrix":
        return matrix(runs, args["stage"], args["kinds"].split(","))
    if kind == "restart":
        return restart(runs, args["stage"], args["kind"])
    raise SystemExit(f"unknown block type: {kind}")


def update(doc: Path, runs: list[dict]) -> int:
    count = 0

    def fill(m: re.Match) -> str:
        nonlocal count
        count += 1
        args = dict(a.split("=", 1) for a in m["args"].split())
        return m.group(1) + "\n" + render(runs, m["type"], args) + "\n" + m.group(5)

    doc.write_text(BLOCK.sub(fill, doc.read_text()))
    return count


if __name__ == "__main__":
    results = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
    doc = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/RESULTS.md")
    runs = load_all(results)
    print(f"{len(runs)} runs read; {update(doc, runs)} blocks updated in {doc}")
