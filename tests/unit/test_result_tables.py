"""loadtest/result_tables.py: compact stats from fake run folders, tables from those stats, in-place block updates."""

import json
from pathlib import Path

from loadtest import result_tables as rt


def make_run(root: Path, name: str, rtts, server=(1.0, 2.0), started=4, stored=4, lost=0, ping="14.0/15.0/16.0"):
    d = root / name
    d.mkdir(parents=True)
    (d / "db_summary.txt").write_text(
        f"stored rows: {stored}   rows with stored_at: {stored}\n"
        f"server time = x: avg {server[0]} ms, slowest 5% (p95) {server[1]} ms\n"
        f"lost readings = sum over devices of (max(seq)-min(seq)+1) - count(distinct seq): {lost}\n"
    )
    (d / "generator_summary.json").write_text(json.dumps({
        "started": started, "results": {"ok": len(rtts), "timeout": 1, "error": 0}, "achieved_rate": 10.0,
        "lag_p99_ms": 0.2, "lag_max_ms": 3.0, "max_in_flight": 5,
    }))
    (d / "generator_log.csv").write_text(
        "device_id,seq,send_time_utc,result,rtt_ms\n"
        + "".join(f"d,{i},t,ok,{v}\n" for i, v in enumerate(rtts))
        + "d,99,t,timeout,2000\n"
    )
    (d / "ping.txt").write_text(f"rtt min/avg/max/mdev = {ping}/1 ms\n")
    return d


def build(tmp_path):
    make_run(tmp_path, "2026-01-01_A_http_10per-s_run1", [10, 20, 30, 40], server=(1.0, 2.0))
    make_run(tmp_path, "2026-01-01_A_http_10per-s_run2", [20, 20, 20, 20], server=(3.0, 4.0), stored=3)
    make_run(tmp_path, "2026-01-01_A_mqtt-1conn_10per-s_run1", [5, 5, 5, 5])
    d = make_run(tmp_path, "2026-01-01_A_mqtt-100conn-restart_100per-s_run1", [10, 20], started=12000, stored=12000)
    (d / "restart_summary.txt").write_text("run\n21.16,18:34:13.494,18:34:34.649\n")
    (d / "worker_restart.txt").write_text(
        "stop_requested=2026-11-10T18:34:03.428Z\nstop_returned=2026-11-10T18:34:13.622Z\n"
        "start_requested=2026-11-10T18:34:33.626Z\nstart_returned=2026-11-10T18:34:34.271Z\n"
    )
    (d / "stored_per_second.csv").write_text("second_utc,stored\n18:34:13,50\n18:34:34,269\n18:34:35,710\n18:34:36,100\n")
    return rt.write_stats(tmp_path)


def test_stats_and_matrix_from_csv(tmp_path):
    assert build(tmp_path) == (4, 1)
    runs = rt.read_csv(tmp_path / "run_stats.csv")
    first = next(r for r in runs if r["run"].endswith("A_http_10per-s_run1"))
    assert (first["sent"], first["ok"], first["timeout"], first["rtt_median_ms"], first["rtt_p99_ms"]) == ("4", "4", "1", "25.0", "40.0")
    out = rt.matrix(runs, "A", ["http"])
    assert "| 10 | http | 2 | 2.00 (1.00-3.00) | 3.00 (2.00-4.00) | 22.5 (20.0-25.0) |" in out
    assert out.rstrip().endswith("| 14.0 | 1 | 0 |")  # one reading missing (sent 4, stored 3), timeouts are not round trips
    assert "mqtt-1conn" not in out


def test_restart_table_and_merge_keeps_absent_runs(tmp_path):
    build(tmp_path)
    out = rt.restart(rt.read_csv(tmp_path / "run_stats.csv"), rt.read_csv(tmp_path / "restart_stats.csv"), "A", "mqtt-100conn-restart")
    assert "| 1 | 21.16 | 12000 | 12000 | 0 | 0 | 2 | 710 |" in out
    for folder in tmp_path.iterdir():
        if folder.is_dir():
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()
    assert rt.write_stats(tmp_path) == (0, 0)  # raw folders gone (archived): the stats lines are kept
    assert len(rt.read_csv(tmp_path / "run_stats.csv")) == 4


def test_update_replaces_only_marked_blocks(tmp_path):
    build(tmp_path)
    doc = tmp_path / "doc.md"
    doc.write_text("intro\n<!-- result_tables: matrix stage=A kinds=http -->\nOLD\n<!-- /result_tables -->\noutro\n")
    n = rt.update(doc, rt.read_csv(tmp_path / "run_stats.csv"), rt.read_csv(tmp_path / "restart_stats.csv"))
    text = doc.read_text()
    assert n == 1 and text.startswith("intro\n") and text.endswith("outro\n") and "OLD" not in text
    assert "| 10 | http | 2 |" in text


def make_queue_run(root: Path, name: str, workers: int, drain: str, stored_per_s: str, samples):
    d = make_run(root, name, [10, 20, 30, 40], server=(4.0, 5.0))
    with open(d / "db_summary.txt", "a") as f:
        f.write(f"rows with stored_at NULL: 0\n{drain}\nworkers: {workers}\nstoring took 100.0 s from the first to the last stored_at, stored per second: {stored_per_s}\n")
    (d / "queue_depth.csv").write_text("time_utc,visible,not_visible\n" + "".join(f"t,{v},10\n" for v in samples))
    return d


def test_queue_stats_and_table(tmp_path):
    make_queue_run(tmp_path, "2026-01-01_C_mqtt-100conn_500per-s_run1", 1, "queue drained after 580 s", "104.0", [0, 9000, 11500, 0])
    make_queue_run(tmp_path, "2026-01-01_C_mqtt-100conn_500per-s_run2", 1, "queue drained after 600 s", "100.0", [0, 8000, 0])
    make_queue_run(tmp_path, "2026-01-01_C_mqtt-100conn-w2_500per-s_run1", 2, "queue drained after 46 s", "207.2", [0, 8195, 0])
    make_run(tmp_path, "2026-01-01_A_http_10per-s_run1", [10, 20])  # no queue_depth.csv: not a Stage C run
    assert rt.write_stats(tmp_path) == (4, 0)
    queues = rt.read_csv(tmp_path / "queue_stats.csv")
    assert len(queues) == 3
    first = next(q for q in queues if q["run"].endswith("C_mqtt-100conn_500per-s_run1"))
    assert (first["workers"], first["queue_peak"], first["drain_s"], first["stored_per_s"]) == ("1", "11500", "580", "104.0")
    out = rt.queue(rt.read_csv(tmp_path / "run_stats.csv"), queues, "C", ["mqtt-100conn", "mqtt-100conn-w2"])
    lines = out.splitlines()
    assert lines[2].startswith("| 1 | 500 | mqtt-100conn | 2 |")
    assert "| 9750 (8000-11500) | 590 (580-600) | 102.0 (100.0-104.0) | 0 |" in lines[2]
    assert lines[3].startswith("| 2 | 500 | mqtt-100conn-w2 | 1 |") and "| 8195 | 46 | 207.2 | 0 |" in lines[3]
    assert len(lines) == 4  # the A run is not in the table


def test_queue_run_that_did_not_drain_and_missing_fields(tmp_path):
    make_queue_run(tmp_path, "2026-01-01_C_mqtt-100conn_500per-s_run1", 1, "queue did not drain within 900 s", "", [5, 50])
    rt.write_stats(tmp_path)
    q = rt.read_csv(tmp_path / "queue_stats.csv")[0]
    assert (q["drain_s"], q["stored_per_s"], q["queue_peak"]) == ("not drained", "", "50")
    out = rt.queue(rt.read_csv(tmp_path / "run_stats.csv"), [q], "C", ["mqtt-100conn"])
    assert "| not drained | n/a | 0 |" in out


def test_update_fills_a_queue_block_and_old_calls_still_work(tmp_path):
    make_queue_run(tmp_path, "2026-01-01_C_mqtt-100conn_500per-s_run1", 1, "queue drained after 580 s", "104.0", [0, 9000])
    rt.write_stats(tmp_path)
    doc = tmp_path / "doc.md"
    doc.write_text("<!-- result_tables: queue stage=C kinds=mqtt-100conn -->\nOLD\n<!-- /result_tables -->\n")
    runs, restarts = rt.read_csv(tmp_path / "run_stats.csv"), rt.read_csv(tmp_path / "restart_stats.csv")
    assert rt.update(doc, runs, restarts, rt.read_csv(tmp_path / "queue_stats.csv")) == 1
    assert "| 1 | 500 | mqtt-100conn | 1 |" in doc.read_text() and "OLD" not in doc.read_text()
    assert rt.update(doc, runs, restarts) == 1  # the three-argument form still works; the table is just empty
    assert "| 1 | 500 |" not in doc.read_text()


def test_no_queue_file_is_written_for_stage_a_and_b_only(tmp_path):
    build(tmp_path)
    assert not (tmp_path / "queue_stats.csv").exists()
