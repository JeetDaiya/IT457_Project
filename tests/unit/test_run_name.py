"""The readable run folder name built by loadtest/run_name.sh (shared by the wrappers and measure_run.sh)."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "loadtest" / "run_name.sh"


def suffix(args, env=None):
    cmd = f'. "{SCRIPT}"; run_suffix {args}'
    out = subprocess.run(
        ["bash", "-c", cmd], capture_output=True, text=True, check=True, env=env or {}
    )
    return out.stdout.strip()


@pytest.mark.parametrize(
    "args, env, expected",
    [
        ("a http 100 1", {}, "A_http_100per-s_run1"),
        ("b http 10 3", {}, "B_http_10per-s_run3"),
        ("a mqtt 500 2", {}, "A_mqtt-1conn_500per-s_run2"),
        ("aconn100 mqtt 50 1", {"STAGE_NAME": "A", "CONNECTIONS": "100"}, "A_mqtt-100conn_50per-s_run1"),
        (
            "arestart mqtt 100 3",
            {"STAGE_NAME": "A", "CONNECTIONS": "100", "RUN_NOTE": "restart"},
            "A_mqtt-100conn-restart_100per-s_run3",
        ),
        ("smoke mqtt 10 1", {"STAGE_NAME": "", "RUN_NOTE": ""}, "smoke_mqtt-1conn_10per-s_run1"),
        ("cal http 500 1", {}, "cal_http_500per-s_run1"),
    ],
)
def test_run_suffix(args, env, expected):
    assert suffix(args, env) == expected
