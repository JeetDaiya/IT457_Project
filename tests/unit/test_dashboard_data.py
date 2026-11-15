"""loadtest/dashboard_data.py: means and sums per setting from fake stats files."""

import json

from loadtest import dashboard_data as dd
from loadtest.result_tables import QUEUE_COLS, RESTART_COLS, RUN_COLS


def write_csv(path, cols, rows):
    lines = [",".join(cols)] + [",".join(str(r.get(c, 0)) for c in cols) for r in rows]
    path.write_text("\n".join(lines) + "\n")


def run(repeat, sent, stored, server, stage="B", kind="http", rate=500):
    return {
        "run": f"{stage}-{kind}-{repeat}",
        "stage": stage,
        "kind": kind,
        "rate": rate,
        "repeat": repeat,
        "sent": sent,
        "stored": stored,
        "missing": sent - stored,
        "server_avg_ms": server,
        "server_p95_ms": 1,
        "rtt_median_ms": 2,
        "rtt_p95_ms": 3,
        "ping_min_ms": 2,
    }


def test_build_aggregates_repeats_and_reads_restarts(tmp_path):
    write_csv(
        tmp_path / "run_stats.csv",
        RUN_COLS,
        [run(1, 100, 60, 10.0), run(2, 100, 80, 20.0)],
    )
    write_csv(
        tmp_path / "restart_stats.csv",
        RESTART_COLS,
        [
            {
                "run": "r1",
                "stage": "A",
                "kind": "k",
                "rate": 100,
                "repeat": 1,
                "gap_s": 21.1,
                "seconds_above_110pct": 5,
                "peak_stored_per_s": 735,
            },
        ],
    )
    data = dd.build(tmp_path)
    (row,) = data["matrix"]
    assert (row["stage"], row["kind"], row["rate"], row["runs"]) == (
        "B",
        "http",
        500,
        2,
    )
    assert (row["sent"], row["stored"], row["missing"]) == (200, 140, 60)
    assert row["server_avg_ms"] == 15.0
    assert row["stored_pct"] == 70.0
    assert data["restart"] == [
        {
            "stage": "A",
            "repeat": 1,
            "gap_s": 21.1,
            "seconds_above_110pct": 5,
            "peak_stored_per_s": 735,
        }
    ]


def test_main_writes_json(tmp_path):
    write_csv(tmp_path / "run_stats.csv", RUN_COLS, [run(1, 10, 10, 1.0)])
    write_csv(tmp_path / "restart_stats.csv", RESTART_COLS, [])
    out = tmp_path / "out.json"
    assert dd.main([str(tmp_path), str(out)]) == 0
    assert json.loads(out.read_text())["matrix"][0]["stored_pct"] == 100.0


def test_check_runs_dropped_queue_means_and_empty_restart_peak(tmp_path):
    w1 = [run(i, 600, 600, 4.3, "C", "mqtt-100conn") for i in (1, 2)]
    check = run(1, 150, 150, 4.3, "C", "mqtt-100conn-check")
    write_csv(tmp_path / "run_stats.csv", RUN_COLS, [*w1, check])
    write_csv(
        tmp_path / "restart_stats.csv",
        RESTART_COLS,
        [
            {
                "run": "r",
                "stage": "C",
                "repeat": 1,
                "gap_s": 22.9,
                "peak_stored_per_s": "",
            }
        ],
    )
    write_csv(
        tmp_path / "queue_stats.csv",
        QUEUE_COLS,
        [
            {
                "run": w1[0]["run"],
                "workers": 1,
                "queue_peak": 100,
                "drain_s": 40,
                "stored_per_s": 103.5,
            },
            {
                "run": w1[1]["run"],
                "workers": 1,
                "queue_peak": 200,
                "drain_s": 50,
                "stored_per_s": 104.5,
            },
            {
                "run": check["run"],
                "workers": "",
                "queue_peak": 9,
                "drain_s": "",
                "stored_per_s": "",
            },
        ],
    )
    data = dd.build(tmp_path)
    assert [m["kind"] for m in data["matrix"]] == ["mqtt-100conn"]
    assert data["restart"][0]["peak_stored_per_s"] is None
    assert data["queue"] == [
        {
            "stage": "C",
            "kind": "mqtt-100conn",
            "rate": 500,
            "workers": 1,
            "runs": 2,
            "queue_peak": 150.0,
            "drain_s": 45.0,
            "stored_per_s": 104.0,
        }
    ]
