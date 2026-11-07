"""MQTT load generator: argument rules, scheduling, ack handling and the log files.

Most tests swap paho's Client for a fake; one end-to-end test uses the stub broker.
"""

from __future__ import annotations

import csv
import json
import threading
from collections import defaultdict

import pytest

from app.rules import Reading
from loadtest import mqtt_generator as gen
from loadtest.readings import LOG_HEADER
from loadtest.stub_mqtt_broker import StubBroker

SUMMARY_KEYS = {
    "planned",
    "started",
    "logged",
    "results",
    "target_rate",
    "achieved_rate",
    "rate_ratio",
    "lag_p50_ms",
    "lag_p99_ms",
    "lag_max_ms",
    "max_in_flight",
    "pool",
    "connections",
    "wall_s",
    "meets_rate_rule",
}


class Result:
    def __init__(self, mid: int, rc: int = 0):
        self.mid = mid
        self.rc = rc


class Env:
    """Shared record of what the fake clients saw, plus how they behave."""

    def __init__(self):
        self.mode = "sync"  # sync | timer | never | rc | raise
        self.fail_every = 0  # in rc/raise mode, fail every n-th publish (0 = all)
        self.connect_error: Exception | None = None
        self.connect_ok = True
        self.clients: list = []
        self.publishes: list[dict] = []
        self.lock = threading.Lock()


class FakeClient:
    env: Env

    def __init__(self, client_id=None, clean_session=True, userdata=None, **_):
        self.client_id = client_id
        self.clean_session = clean_session
        self.userdata = userdata
        self.on_connect = None
        self.on_publish = None
        self.calls: dict[str, tuple] = {}
        self.stopped = False
        self._mid = 0
        self.mids: list[int] = []
        self.count = 0
        self.env.clients.append(self)

    def connect(self, host, port, keepalive=60):
        self.calls["connect"] = (host, port, keepalive)
        if self.env.connect_error:
            raise self.env.connect_error

    def loop_start(self):
        self.calls["loop_start"] = ()
        if self.env.connect_ok and self.on_connect:
            self.on_connect(self, self.userdata, {}, 0)

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        self.stopped = True

    def max_inflight_messages_set(self, n):
        self.calls["inflight"] = (n,)

    def max_queued_messages_set(self, n):
        self.calls["queued"] = (n,)

    def reconnect_delay_set(self, min_delay, max_delay):
        self.calls["reconnect"] = (min_delay, max_delay)

    def _ack(self, mid):
        if self.on_publish:
            self.on_publish(self, self.userdata, mid)

    def publish(self, topic, payload, qos=0):
        env = self.env
        self._mid += 1
        self.count += 1
        mid = self._mid
        with env.lock:
            env.publishes.append(
                {
                    "client": self.userdata,
                    "topic": topic,
                    "payload": payload,
                    "qos": qos,
                }
            )
        self.mids.append(mid)
        failing = env.mode in ("rc", "raise") and (
            env.fail_every == 0 or self.count % env.fail_every == 0
        )
        if failing and env.mode == "raise":
            raise RuntimeError("boom")
        if failing:
            return Result(mid, rc=4)
        if env.mode in ("sync", "rc", "raise"):
            self._ack(mid)
        elif env.mode == "timer":
            t = threading.Timer(0.01, self._ack, args=(mid,))
            t.daemon = True
            t.start()
        return Result(mid)


@pytest.fixture
def env(monkeypatch):
    e = Env()
    client_cls = type("BoundFake", (FakeClient,), {"env": e})
    monkeypatch.setattr(gen.mqtt, "Client", client_cls)
    return e


def args(tmp_path, *extra, rate=20, duration=1, tag="t1"):
    argv = [
        "--rate", str(rate), "--duration", str(duration), "--tag", tag,
        "--out-dir", str(tmp_path / "out"),
    ]  # fmt: skip
    return gen.parse_args(argv + [str(x) for x in extra])


def read_log(opts):
    with open(f"{opts.out_dir}/generator_log.csv", newline="") as f:
        return list(csv.reader(f))


# ---- parse_args ------------------------------------------------------------


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("MQTT_PORT", raising=False)
    o = args(tmp_path)
    assert (o.duration, o.devices, o.seed, o.connections, o.inflight) == (
        1, 100, 1, 1, 0,
    )  # fmt: skip
    assert (o.host, o.port, o.rate, o.tag) == ("localhost", 1883, 20, "t1")


def test_host_and_port_from_env_and_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "broker.example")
    monkeypatch.setenv("MQTT_PORT", "2883")
    o = args(tmp_path)
    assert (o.host, o.port) == ("broker.example", 2883)
    o = args(tmp_path, "--host", "h2", "--port", 1999)
    assert (o.host, o.port) == ("h2", 1999)


def test_duration_default_is_120(tmp_path):
    o = gen.parse_args(["--rate", "5", "--tag", "x", "--out-dir", str(tmp_path / "o")])
    assert o.duration == 120


@pytest.mark.parametrize(
    "extra, kw",
    [
        ([], {"rate": 0}),
        ([], {"rate": -3}),
        ([], {"duration": 0}),
        ([], {"rate": 1001, "duration": 100}),
        (["--devices", 0], {}),
        (["--devices", 101], {}),
        (["--connections", 0], {}),
        (["--devices", 2, "--connections", 3], {}),
        (["--inflight", -1], {}),
    ],
)
def test_invalid_arguments_exit_2(tmp_path, extra, kw):
    with pytest.raises(SystemExit) as exc:
        args(tmp_path, *extra, **kw)
    assert exc.value.code == 2


def test_message_cap_boundary_is_allowed(tmp_path):
    assert args(tmp_path, rate=1000, duration=100).rate == 1000


@pytest.mark.parametrize("missing", ["--rate", "--tag", "--out-dir"])
def test_required_flags(missing):
    full = {"--rate": "5", "--tag": "x", "--out-dir": "/tmp/never-made"}
    argv = [part for k, v in full.items() if k != missing for part in (k, v)]
    with pytest.raises(SystemExit) as exc:
        gen.parse_args(argv)
    assert exc.value.code == 2


def test_refuses_out_dir_with_existing_log(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "generator_log.csv").write_text("keep me\n")
    with pytest.raises(SystemExit) as exc:
        args(tmp_path)
    assert exc.value.code == 2
    assert (out / "generator_log.csv").read_text() == "keep me\n"


def test_topic():
    assert gen.topic("t1-dev-0007") == "vitals/t1-dev-0007"


# ---- clients and connection ------------------------------------------------


def test_one_client_per_connection_with_settings(env, tmp_path):
    o = args(tmp_path, "--connections", 3, "--host", "hh", "--port", 1999)
    gen.run(o)
    assert [c.client_id for c in env.clients] == ["t1-gen-0", "t1-gen-1", "t1-gen-2"]
    assert len({c.client_id for c in env.clients}) == 3
    for i, c in enumerate(env.clients):
        assert c.clean_session is True
        assert c.userdata == i
        assert c.calls["inflight"] == (40,)  # 2 x rate
        assert c.calls["queued"] == (0,)
        assert c.calls["reconnect"] == (1, 5)
        assert c.calls["connect"] == ("hh", 1999, 60)
        assert c.stopped


def test_explicit_inflight_is_used_and_reported(env, tmp_path):
    summary = gen.run(args(tmp_path, "--inflight", 7))
    assert env.clients[0].calls["inflight"] == (7,)
    assert summary["pool"] == 7


def test_connect_oserror_raises_connection_error(env, tmp_path):
    env.connect_error = OSError("refused")
    with pytest.raises(ConnectionError):
        gen.run(args(tmp_path))
    assert env.publishes == []


def test_no_connack_raises_connection_error(env, tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "CONNECT_TIMEOUT_S", 0.2)
    env.connect_ok = False
    with pytest.raises(ConnectionError):
        gen.run(args(tmp_path))
    assert env.publishes == []
    assert all(c.stopped for c in env.clients)


def test_main_returns_1_on_connection_error(env, tmp_path, capsys):
    env.connect_error = OSError("refused")
    code = gen.main(
        ["--rate", "20", "--duration", "1", "--tag", "t1",
         "--out-dir", str(tmp_path / "out")]
    )  # fmt: skip
    assert code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert captured.out == ""


def test_main_prints_one_json_line_and_returns_0(env, tmp_path, capsys):
    code = gen.main(
        ["--rate", "20", "--duration", "1", "--tag", "t1",
         "--out-dir", str(tmp_path / "out")]
    )  # fmt: skip
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert set(json.loads(lines[0])) == SUMMARY_KEYS


# ---- what is published -----------------------------------------------------


def test_publish_shape_seq_and_device_connection_mapping(env, tmp_path):
    o = args(tmp_path, "--devices", 5, "--connections", 2, rate=50, duration=1)
    gen.run(o)
    assert len(env.publishes) == 50
    seqs = defaultdict(list)
    conns = defaultdict(set)
    for p in env.publishes:
        assert p["qos"] == 1
        payload = p["payload"]
        raw = payload.encode() if isinstance(payload, str) else payload
        assert len(raw) < 200
        reading = Reading.model_validate_json(raw)
        assert p["topic"] == f"vitals/{reading.device_id}"
        assert reading.device_id.startswith("t1-dev-")
        seqs[reading.device_id].append(reading.seq)
        conns[reading.device_id].add(p["client"])
    assert sorted(seqs) == [f"t1-dev-{n:04d}" for n in range(1, 6)]
    for dev, s in seqs.items():
        assert s == list(range(1, 11)), dev
    for dev, used in conns.items():
        assert len(used) == 1
        assert used == {(int(dev[-4:]) - 1) % 2}


def test_first_message_goes_to_device_one_in_order(env, tmp_path):
    gen.run(args(tmp_path, rate=20, duration=1))
    first = json.loads(env.publishes[0]["payload"])
    assert first["device_id"] == "t1-dev-0001"
    assert first["seq"] == 1
    assert first["patient_ref"] == "P0001"


# ---- results ---------------------------------------------------------------


def test_sync_ack_before_publish_returns_counts_ok(env, tmp_path):
    o = args(tmp_path)
    s = gen.run(o)
    assert s["results"] == {"ok": 20, "duplicate": 0, "timeout": 0, "error": 0}
    assert s["planned"] == s["started"] == s["logged"] == 20


def test_delayed_ack_counts_ok_with_positive_rtt(env, tmp_path):
    env.mode = "timer"
    o = args(tmp_path)
    s = gen.run(o)
    assert s["results"]["ok"] == 20
    rows = read_log(o)[1:]
    assert all(r[3] == "ok" and float(r[4]) >= 5 for r in rows)


def test_no_ack_gives_timeout_rows_and_late_ack_adds_nothing(
    env, tmp_path, monkeypatch
):
    monkeypatch.setattr(gen, "TIMEOUT_S", 0.3)
    env.mode = "never"
    o = args(tmp_path)
    s = gen.run(o)
    assert s["results"] == {"ok": 0, "duplicate": 0, "timeout": 20, "error": 0}
    assert s["logged"] == 20
    before = read_log(o)
    for c in env.clients:
        for mid in c.mids:
            c._ack(mid)
    assert read_log(o) == before
    assert len(before) == 21
    summary = json.loads((tmp_path / "out" / "generator_summary.json").read_text())
    assert summary["results"]["timeout"] == 20


@pytest.mark.parametrize("mode", ["rc", "raise"])
def test_publish_failures_are_error_rows_and_run_continues(env, tmp_path, mode):
    env.mode = mode
    env.fail_every = 4
    o = args(tmp_path)
    s = gen.run(o)
    assert s["results"]["error"] == 5
    assert s["results"]["ok"] == 15
    assert s["started"] == s["logged"] == s["planned"] == 20
    assert len(env.publishes) == 20
    errors = [r for r in read_log(o)[1:] if r[3] == "error"]
    assert len(errors) == 5


def test_all_publishes_failing_still_logs_everything(env, tmp_path):
    env.mode = "rc"
    s = gen.run(args(tmp_path))
    assert s["results"]["error"] == 20
    assert s["logged"] == 20


# ---- files and summary -----------------------------------------------------


def test_files_written_and_consistent(env, tmp_path):
    o = args(tmp_path, rate=40, duration=1)
    s = gen.run(o)
    out = tmp_path / "out"
    rows = read_log(o)
    assert rows[0] == LOG_HEADER
    assert len(rows) - 1 == 40
    for device_id, seq, stamp, result, rtt in rows[1:]:
        assert device_id.startswith("t1-dev-")
        assert int(seq) >= 1
        assert stamp.endswith("Z")
        assert result == "ok"
        assert float(rtt) >= 0
        assert len(rtt.split(".")[-1]) == 1
    settings = json.loads((out / "settings.json").read_text())
    for key in (
        "host", "port", "rate", "duration", "tag", "devices", "seed",
        "connections", "inflight", "timeout_s", "start_utc", "python", "machine",
    ):  # fmt: skip
        assert key in settings
    assert settings["rate"] == 40
    assert settings["tag"] == "t1"
    assert json.loads((out / "generator_summary.json").read_text()) == s


def test_summary_fields(env, tmp_path):
    o = args(tmp_path, "--connections", 2, rate=40, duration=1)
    s = gen.run(o)
    assert set(s) == SUMMARY_KEYS
    assert set(s["results"]) == {"ok", "duplicate", "timeout", "error"}
    assert sum(s["results"].values()) == s["logged"] == s["planned"] == 40
    assert s["target_rate"] == 40
    assert s["connections"] == 2
    assert s["pool"] == 80
    assert s["rate_ratio"] == pytest.approx(s["achieved_rate"] / 40, rel=0.02)
    assert s["lag_p50_ms"] <= s["lag_p99_ms"] <= s["lag_max_ms"]
    assert s["meets_rate_rule"] == (
        s["rate_ratio"] >= gen.RATE_LIMIT and s["lag_p99_ms"] < gen.LAG_LIMIT_MS
    )
    assert s["wall_s"] >= 0.9  # fixed schedule: 40 messages at 40/s take ~1 s


def test_schedule_is_open_loop_even_without_acks(env, tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "TIMEOUT_S", 0.3)
    env.mode = "never"
    s = gen.run(args(tmp_path))
    assert s["started"] == 20
    assert s["max_in_flight"] >= 5  # 0.3 s timeout at 20/s: acks never awaited


def test_constants():
    assert gen.MAX_MESSAGES == 100_000
    assert gen.SEEDED_PATIENTS == 100
    assert gen.LAG_LIMIT_MS == 50.0
    assert gen.RATE_LIMIT == 0.99


# ---- end to end with the stub broker and real paho -------------------------


def test_end_to_end_against_stub_broker(tmp_path):
    with StubBroker(delay=0.05) as broker:
        o = gen.parse_args(
            ["--rate", "20", "--duration", "2", "--tag", "e2e",
             "--host", "127.0.0.1", "--port", str(broker.port),
             "--connections", "1", "--out-dir", str(tmp_path / "out")]
        )  # fmt: skip
        s = gen.run(o)
        count = broker.publish_count
    assert set(s) == SUMMARY_KEYS
    assert s["planned"] == s["logged"] == 40
    assert s["results"] == {"ok": 40, "duplicate": 0, "timeout": 0, "error": 0}
    assert count == 40
    rows = read_log(o)
    assert rows[0] == LOG_HEADER
    assert len(rows) == 41
    assert all(float(r[4]) >= 45 for r in rows[1:])
