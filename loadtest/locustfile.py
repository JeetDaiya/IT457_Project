"""Open-loop HTTP load generator for POST /readings (run via loadtest/run_http.sh).

One Locust user runs the whole schedule: message n is due at start + n * interval.
Each send is spawned on time and the loop never waits for the reply, so a slow server
shows up as longer round trips and more requests in flight, not as a lower send rate.
All timing here comes from this machine's own clock.
"""

import csv
import json
import math
import platform
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import gevent
import gevent.pool
import gevent.timeout
import locust
from locust import FastHttpUser, events, task
from locust.exception import StopUser

from loadtest.readings import LOG_HEADER, make_reading, to_json, utc_stamp

MAX_MESSAGES = 100_000
SEEDED_PATIENTS = 100  # SEED_PATIENTS default; a device maps to patient P{index}
TIMEOUT_S = 2.0
LAG_LIMIT_MS = 50.0
RATE_LIMIT = 0.99


@events.init_command_line_parser.add_listener
def _add_arguments(parser):
    parser.add_argument("--rate", type=int, required=True, help="messages per second")
    parser.add_argument("--duration", type=int, default=120, help="seconds")
    parser.add_argument("--tag", required=True, help="run tag put in device_id")
    parser.add_argument("--devices", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out-dir", required=True, help="new folder for this run")
    parser.add_argument(
        "--pool", type=int, default=0, help="max connections (default 2 x rate)"
    )


@events.init.add_listener
def _validate(environment, **_):
    opts = environment.parsed_options
    if opts.rate < 1 or opts.duration < 1:
        sys.exit("error: --rate and --duration must be at least 1")
    if opts.rate * opts.duration > MAX_MESSAGES:
        sys.exit(f"error: rate x duration exceeds {MAX_MESSAGES} messages")
    if not 1 <= opts.devices <= SEEDED_PATIENTS:
        sys.exit(f"error: --devices must be 1..{SEEDED_PATIENTS} (seeded patients)")
    if (Path(opts.out_dir) / "generator_log.csv").exists():
        sys.exit(f"error: {opts.out_dir} already holds a run; raw results are kept")


def classify(status_code: int, error: Exception | None) -> str:
    if status_code == 201:
        return "ok"
    if status_code == 200:
        return "duplicate"
    cause = getattr(error, "original", error)  # geventhttpclient wraps the real error
    if isinstance(cause, TimeoutError | gevent.timeout.Timeout):
        return "timeout"
    return "error"


def _percentile(sorted_values: list[float], share: float) -> float:
    return sorted_values[max(0, math.ceil(share * len(sorted_values)) - 1)]


class OpenLoopUser(FastHttpUser):
    network_timeout = TIMEOUT_S
    connection_timeout = TIMEOUT_S

    def __init__(self, environment):
        opts = environment.parsed_options
        self.concurrency = opts.pool or 2 * opts.rate
        super().__init__(environment)

    @task
    def run_schedule(self):
        opts = self.environment.parsed_options
        out_dir = Path(opts.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        settings = {
            "host": self.host,
            "rate": opts.rate,
            "duration": opts.duration,
            "tag": opts.tag,
            "devices": opts.devices,
            "seed": opts.seed,
            "pool": self.concurrency,
            "timeout_s": TIMEOUT_S,
            "start_utc": utc_stamp(datetime.now(UTC)),
            "locust": locust.__version__,
            "python": platform.python_version(),
            "machine": platform.machine(),
        }
        (out_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")

        interval = 1.0 / opts.rate
        total = opts.rate * opts.duration
        rng = random.Random(opts.seed)
        seqs = [0] * opts.devices
        lags, sent_at = [], []
        logged = {"rows": 0}
        with open(out_dir / "generator_log.csv", "w", newline="") as log_file:
            log = csv.writer(log_file)
            log.writerow(LOG_HEADER)
            counts = {"ok": 0, "duplicate": 0, "timeout": 0, "error": 0}
            in_flight = {"now": 0, "max": 0}

            def send(reading, due):
                moment = datetime.now(UTC)
                reading["sent_at"] = utc_stamp(moment)
                body = to_json(reading)
                in_flight["now"] += 1
                in_flight["max"] = max(in_flight["max"], in_flight["now"])
                t0 = time.perf_counter()
                lags.append(t0 - due)
                sent_at.append(t0)
                try:
                    with self.client.post(
                        "/readings",
                        data=body,
                        headers={"Content-Type": "application/json"},
                        catch_response=True,
                    ) as response:
                        result = classify(
                            response.status_code, getattr(response, "error", None)
                        )
                        if result in ("ok", "duplicate"):
                            response.success()
                        else:
                            response.failure(result)
                except Exception:  # noqa: BLE001 - a failed send must never stop the loop
                    result = "error"
                rtt_ms = (time.perf_counter() - t0) * 1000
                in_flight["now"] -= 1
                counts[result] += 1
                log.writerow(
                    [
                        reading["device_id"],
                        reading["seq"],
                        reading["sent_at"],
                        result,
                        f"{rtt_ms:.1f}",
                    ]
                )
                logged["rows"] += 1

            group = gevent.pool.Group()
            start = time.perf_counter()
            for n in range(total):
                due = start + n * interval
                gevent.sleep(max(0.0, due - time.perf_counter()))
                index = n % opts.devices
                seqs[index] += 1
                reading = make_reading(
                    rng, opts.tag, index + 1, seqs[index], datetime.now(UTC)
                )
                group.spawn(send, reading, due)
            group.join(timeout=TIMEOUT_S + 1)

        sorted_lags = sorted(max(0.0, lag) for lag in lags)
        span = max(sent_at) - min(sent_at) if len(sent_at) > 1 else 0.0
        achieved = (len(sent_at) - 1) / span if span > 0 else 0.0
        summary = {
            "planned": total,
            "started": len(sent_at),
            "logged": logged["rows"],
            "results": counts,
            "target_rate": opts.rate,
            "achieved_rate": round(achieved, 2),
            "rate_ratio": round(achieved / opts.rate, 4),
            "lag_p50_ms": round(_percentile(sorted_lags, 0.50) * 1000, 2),
            "lag_p99_ms": round(_percentile(sorted_lags, 0.99) * 1000, 2),
            "lag_max_ms": round(sorted_lags[-1] * 1000, 2),
            "max_in_flight": in_flight["max"],
            "pool": self.concurrency,
            "wall_s": round(time.perf_counter() - start, 2),
        }
        summary["meets_rate_rule"] = (
            summary["rate_ratio"] >= RATE_LIMIT and summary["lag_p99_ms"] < LAG_LIMIT_MS
        )
        (out_dir / "generator_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )

        self.environment.process_exit_code = 0
        gevent.spawn(self.environment.runner.quit)
        raise StopUser()
