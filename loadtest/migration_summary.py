"""Numbers for the B -> C migration test, from the cutover log and the per-second storing counts.

    python3 migration_summary.py steps <cutover_steps.txt>
        where the time went (stop, dump, restore, start) and the total stopped time
    python3 migration_summary.py catchup <stored_per_second.csv> <restart HH:MM:SS> <rate>
        seconds after the restart until ten seconds in a row average the load rate (n/a if never)

Stdlib only. All timestamps in the steps file come from the app host's own clock (the same clock as stored_at).
"""

import csv
import sys
from datetime import datetime

# (name, from step, to step): the cutover log has one `key=<UTC timestamp>` line per step
_PARTS = [
    ("stop_s", "stop_requested", "stop_returned"),
    ("dump_s", "dump_start", "dump_end"),
    ("restore_s", "restore_start", "restore_end"),
    ("start_s", "start_requested", "health_ok"),
    ("stopped_s", "stop_requested", "health_ok"),
]
_LABELS = {
    "stop_s": "stop api and worker",
    "dump_s": "pg_dump",
    "restore_s": "pg_restore",
    "start_s": "start on the new database until /health is ok",
    "stopped_s": "stopped in total (stop requested to /health ok)",
}
WINDOW_S = 10  # the backlog is cleared when ten seconds in a row average the load rate
TOLERANCE = 1.05


def parse_steps(text: str) -> dict[str, datetime]:
    """`key=<ISO timestamp>` lines; any other line (sizes, notes, blanks) is ignored."""
    steps: dict[str, datetime] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if "T" not in value:  # a size such as 20260101 would otherwise parse as a date
            continue
        try:
            steps[key.strip()] = datetime.fromisoformat(value)
        except ValueError:
            continue
    return steps


def durations(steps: dict[str, datetime]) -> dict[str, float]:
    result = {}
    for name, start, end in _PARTS:
        for step in (start, end):
            if step not in steps:
                raise ValueError(f"step {step!r} is missing from the cutover log")
        result[name] = (steps[end] - steps[start]).total_seconds()
    return result


def format_breakdown(parts: dict[str, float]) -> str:
    return "\n".join(f"{_LABELS[name]}: {parts[name]:.1f} s" for name, _, _ in _PARTS)


def _seconds(hms: str) -> int:
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


def catch_up_seconds(
    per_second: list[tuple[str, int]], restart_hms: str, rate: float
) -> int | None:
    """Seconds from the restart second to the first second from which the next ten seconds
    average at most rate x 1.05 readings stored per second (the worker has caught up with the
    load). None if that never happens in the data, or less than ten seconds are left to decide.
    A second with nothing stored counts as 0; seconds are HH:MM:SS of one UTC day (no midnight wrap)."""
    start = _seconds(restart_hms)
    counts = {_seconds(second): count for second, count in per_second}
    last = max(counts, default=start)
    for t in range(start, last - WINDOW_S + 2):
        window = sum(counts.get(t + i, 0) for i in range(WINDOW_S))
        if window / WINDOW_S <= rate * TOLERANCE:
            return t - start
    return None


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "steps":
        with open(argv[1]) as f:
            print(format_breakdown(durations(parse_steps(f.read()))))
        return 0
    if len(argv) == 4 and argv[0] == "catchup":
        with open(argv[1]) as f:
            rows = [
                (r["second_utc"], int(r["stored"]))
                for r in csv.DictReader(f)
                if r["second_utc"]  # a reading with stored_at NULL has no second
            ]
        result = catch_up_seconds(rows, argv[2], float(argv[3]))
        print("n/a" if result is None else result)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
