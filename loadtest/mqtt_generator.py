"""Open-loop MQTT load generator (run via loadtest/run_mqtt.sh).

Same idea as locustfile.py: message n is due at start + n * interval, the loop never waits
for an acknowledgement, and all timing comes from this machine's own clock. The round trip
is publish -> PUBACK from the BROKER; it does not include the worker or the database.
"""

import argparse
import csv
import json
import math
import os
import platform
import random
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import paho.mqtt
import paho.mqtt.client as mqtt

from loadtest.readings import LOG_HEADER, make_reading, to_json, utc_stamp

MAX_MESSAGES = 100_000
SEEDED_PATIENTS = 100  # SEED_PATIENTS default; a device maps to patient P{index}
TIMEOUT_S = 2.0
LAG_LIMIT_MS = 50.0
RATE_LIMIT = 0.99
CONNECT_TIMEOUT_S = 10.0
SWEEP_S = 0.1


def topic(device_id: str) -> str:
    return f"vitals/{device_id}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=int, required=True, help="messages per second")
    parser.add_argument("--duration", type=int, default=120, help="seconds")
    parser.add_argument("--tag", required=True, help="run tag put in device_id")
    parser.add_argument("--devices", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out-dir", required=True, help="new folder for this run")
    parser.add_argument("--host", default=os.environ.get("MQTT_HOST", "localhost"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("MQTT_PORT", "1883"))
    )
    parser.add_argument("--connections", type=int, default=1)
    parser.add_argument(
        "--inflight",
        type=int,
        default=0,
        help="max unacknowledged messages per connection (default 2 x rate)",
    )
    opts = parser.parse_args(argv)
    if opts.rate < 1 or opts.duration < 1:
        parser.error("--rate and --duration must be at least 1")
    if opts.rate * opts.duration > MAX_MESSAGES:
        parser.error(f"rate x duration exceeds {MAX_MESSAGES} messages")
    if not 1 <= opts.devices <= SEEDED_PATIENTS:
        parser.error(f"--devices must be 1..{SEEDED_PATIENTS} (seeded patients)")
    if not 1 <= opts.connections <= opts.devices:
        parser.error("--connections must be between 1 and --devices")
    if opts.inflight < 0:
        parser.error("--inflight must not be negative")
    if (Path(opts.out_dir) / "generator_log.csv").exists():
        parser.error(f"{opts.out_dir} already holds a run; raw results are kept")
    return opts


def _percentile(sorted_values: list[float], share: float) -> float:
    return sorted_values[max(0, math.ceil(share * len(sorted_values)) - 1)]


class _Run:
    """State shared by the schedule loop, paho's network threads and the sweeper.

    paho calls on_publish while holding its own lock, so publish() must never be called
    while holding ours. A PUBACK can therefore arrive before the message is registered
    (kept in `early`), and a PUBACK for a message already logged as timeout or error is
    ignored (kept in `abandoned` until it shows up or its packet id is reused).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._log = None  # csv writer, attached once the clients are connected
        self._pending: dict[tuple[int, int], tuple] = {}
        self._early: dict[tuple[int, int], float] = {}
        self._abandoned: set[tuple[int, int]] = set()
        self.counts = {"ok": 0, "duplicate": 0, "timeout": 0, "error": 0}
        self.rows = 0
        self.max_in_flight = 0

    def attach_log(self, writer) -> None:
        self._log = writer

    def _write(self, item: tuple, result: str, now: float) -> None:
        device_id, seq, sent_at, t0 = item
        with self._log_lock:
            self.counts[result] += 1
            self._log.writerow(
                [device_id, seq, sent_at, result, f"{(now - t0) * 1000:.1f}"]
            )
            self.rows += 1

    def failed(self, item: tuple, key: tuple[int, int] | None = None) -> None:
        if key is not None:
            with self._lock:  # paho may still send it after a reconnect
                self._abandoned.add(key)
        self._write(item, "error", time.perf_counter())

    def register(self, key: tuple[int, int], item: tuple) -> None:
        with self._lock:
            self._abandoned.discard(key)  # a reused packet id belongs to this message
            acked_at = self._early.pop(key, None)
            if acked_at is None:
                self._pending[key] = item
                self.max_in_flight = max(self.max_in_flight, len(self._pending))
                return
        self._write(item, "ok", acked_at)

    def acked(self, key: tuple[int, int]) -> None:
        now = time.perf_counter()
        with self._lock:
            item = self._pending.pop(key, None)
            if item is None:
                if key in self._abandoned:
                    self._abandoned.discard(key)
                else:
                    self._early[key] = now
                return
        self._write(item, "ok", now)

    def expire(self, now: float, force: bool = False) -> None:
        with self._lock:
            keys = [
                key
                for key, item in self._pending.items()
                if force or now - item[3] >= TIMEOUT_S
            ]
            items = [self._pending.pop(key) for key in keys]
            self._abandoned.update(keys)
        for item in items:
            self._write(item, "timeout", now)

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)


def _make_client(index: int, opts: argparse.Namespace, run: _Run):
    client = mqtt.Client(
        client_id=f"{opts.tag}-gen-{index}", clean_session=True, userdata=index
    )
    client.max_inflight_messages_set(opts.inflight or 2 * opts.rate)
    client.max_queued_messages_set(0)
    client.reconnect_delay_set(min_delay=1, max_delay=5)
    up = threading.Event()

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            up.set()

    def on_publish(client, userdata, mid):
        run.acked((userdata, mid))

    client.on_connect = on_connect
    client.on_publish = on_publish
    return client, up


def _connect(opts: argparse.Namespace, run: _Run) -> list:
    clients, events = [], []
    try:
        for index in range(opts.connections):
            client, up = _make_client(index, opts, run)
            clients.append(client)
            events.append(up)
            client.connect(opts.host, opts.port, keepalive=60)
            client.loop_start()
        for up in events:
            if not up.wait(CONNECT_TIMEOUT_S):
                raise ConnectionError(
                    f"no CONNACK from {opts.host}:{opts.port} within {CONNECT_TIMEOUT_S:g} s"
                )
    except OSError as exc:
        _close(clients)
        raise ConnectionError(
            f"cannot connect to {opts.host}:{opts.port}: {exc}"
        ) from exc
    except ConnectionError:
        _close(clients)
        raise
    return clients


def _close(clients: list) -> None:
    for client in clients:
        client.loop_stop()
        client.disconnect()


def _send(run: _Run, client, conn: int, reading: dict, payload: str) -> float:
    """Publish one reading and return the send time on the generator's own clock."""
    t0 = time.perf_counter()
    item = (reading["device_id"], reading["seq"], reading["sent_at"], t0)
    try:
        info = client.publish(topic(reading["device_id"]), payload, qos=1)
    except Exception:  # noqa: BLE001 - a failed send must never stop the loop
        run.failed(item)
        return t0
    key = (conn, info.mid)
    if info.rc == mqtt.MQTT_ERR_SUCCESS:
        run.register(key, item)
    else:
        run.failed(item, key)
    return t0


def _sweep(run: _Run, stop: threading.Event) -> None:
    while not stop.wait(SWEEP_S):
        run.expire(time.perf_counter())


def run(opts: argparse.Namespace) -> dict:
    out_dir = Path(opts.out_dir)
    inflight = opts.inflight or 2 * opts.rate
    interval = 1.0 / opts.rate
    total = opts.rate * opts.duration

    state = _Run()
    clients = _connect(opts, state)  # raises ConnectionError; nothing is written yet
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "host": opts.host,
        "port": opts.port,
        "rate": opts.rate,
        "duration": opts.duration,
        "tag": opts.tag,
        "devices": opts.devices,
        "seed": opts.seed,
        "connections": opts.connections,
        "inflight": inflight,
        "timeout_s": TIMEOUT_S,
        "start_utc": utc_stamp(datetime.now(UTC)),
        "paho": paho.mqtt.__version__,
        "python": platform.python_version(),
        "machine": platform.machine(),
    }
    (out_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

    rng = random.Random(opts.seed)
    seqs = [0] * opts.devices
    lags: list[float] = []
    sent_at: list[float] = []
    with open(out_dir / "generator_log.csv", "w", newline="") as log_file:
        log = csv.writer(log_file)
        log.writerow(LOG_HEADER)
        state.attach_log(log)
        stop = threading.Event()
        sweeper = threading.Thread(target=_sweep, args=(state, stop), daemon=True)
        sweeper.start()

        start = time.perf_counter()
        for n in range(total):
            due = start + n * interval
            wait = due - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            index = n % opts.devices
            seqs[index] += 1
            conn = index % opts.connections
            reading = make_reading(
                rng, opts.tag, index + 1, seqs[index], datetime.now(UTC)
            )
            t0 = _send(state, clients[conn], conn, reading, to_json(reading))
            lags.append(t0 - due)
            sent_at.append(t0)

        deadline = time.perf_counter() + TIMEOUT_S + 1
        while state.has_pending() and time.perf_counter() < deadline:
            time.sleep(0.05)
        state.expire(time.perf_counter(), force=True)
        stop.set()
        sweeper.join()
        wall = time.perf_counter() - start
    _close(clients)

    sorted_lags = sorted(max(0.0, lag) for lag in lags)
    span = max(sent_at) - min(sent_at) if len(sent_at) > 1 else 0.0
    achieved = (len(sent_at) - 1) / span if span > 0 else 0.0
    summary = {
        "planned": total,
        "started": len(sent_at),
        "logged": state.rows,
        "results": state.counts,
        "target_rate": opts.rate,
        "achieved_rate": round(achieved, 2),
        "rate_ratio": round(achieved / opts.rate, 4),
        "lag_p50_ms": round(_percentile(sorted_lags, 0.50) * 1000, 2),
        "lag_p99_ms": round(_percentile(sorted_lags, 0.99) * 1000, 2),
        "lag_max_ms": round(sorted_lags[-1] * 1000, 2),
        "max_in_flight": state.max_in_flight,
        "pool": inflight,
        "connections": opts.connections,
        "wall_s": round(wall, 2),
    }
    summary["meets_rate_rule"] = (
        summary["rate_ratio"] >= RATE_LIMIT and summary["lag_p99_ms"] < LAG_LIMIT_MS
    )
    (out_dir / "generator_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary


def main(argv: list[str]) -> int:
    opts = parse_args(argv)
    try:
        summary = run(opts)
    except ConnectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
