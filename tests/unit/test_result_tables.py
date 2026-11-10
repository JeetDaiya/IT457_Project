"""loadtest/result_tables.py: tables built from fake run folders, and in-place block updates."""

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
    (d / "generator_summary.json").write_text(json.dumps({"started": started}))
    (d / "generator_log.csv").write_text(
        "device_id,seq,send_time_utc,result,rtt_ms\n"
        + "".join(f"d,{i},t,ok,{v}\n" for i, v in enumerate(rtts))
        + "d,99,t,timeout,2000\n"
    )
    (d / "ping.txt").write_text(f"rtt min/avg/max/mdev = {ping}/1 ms\n")
    return d


def test_matrix_means_ranges_and_sums(tmp_path):
    make_run(tmp_path, "2026-01-01_A_http_10per-s_run1", [10, 20, 30, 40], server=(1.0, 2.0))
    make_run(tmp_path, "2026-01-01_A_http_10per-s_run2", [20, 20, 20, 20], server=(3.0, 4.0), stored=3, lost=0)
    make_run(tmp_path, "2026-01-01_A_mqtt-1conn_10per-s_run1", [5, 5, 5, 5])
    runs = rt.load_all(tmp_path)
    out = rt.matrix(runs, "A", ["http"])
    assert "| 10 | http | 2 | 2.00 (1.00-3.00) | 3.00 (2.00-4.00) | 22.5 (20.0-25.0) |" in out
    assert out.rstrip().endswith("| 14.0 | 1 | 0 |")  # one reading missing (sent 4, stored 3), timeouts are not rtts
    assert "mqtt-1conn" not in out


def test_restart_row(tmp_path):
    d = make_run(tmp_path, "2026-01-01_A_mqtt-100conn-restart_100per-s_run1", [10, 20], started=12000, stored=12000)
    (d / "restart_summary.txt").write_text("run\n21.16,18:34:13.494,18:34:34.649\n")
    (d / "worker_restart.txt").write_text("start_returned=2026-11-10T18:34:34.271Z\n")
    (d / "stored_per_second.csv").write_text("second_utc,stored\n18:34:13,50\n18:34:34,269\n18:34:35,710\n18:34:36,100\n")
    out = rt.restart(rt.load_all(tmp_path), "A", "mqtt-100conn-restart")
    assert "| 1 | 21.16 | 12000 | 12000 | 0 | 0 | 2 | 710 |" in out


def test_update_replaces_only_marked_blocks(tmp_path):
    make_run(tmp_path / "r", "2026-01-01_A_http_10per-s_run1", [10, 20])
    doc = tmp_path / "doc.md"
    doc.write_text(
        "intro\n<!-- result_tables: matrix stage=A kinds=http -->\nOLD\n<!-- /result_tables -->\noutro\n"
    )
    assert rt.update(doc, rt.load_all(tmp_path / "r")) == 1
    text = doc.read_text()
    assert text.startswith("intro\n") and text.endswith("outro\n") and "OLD" not in text
    assert "| 10 | http | 1 |" in text
