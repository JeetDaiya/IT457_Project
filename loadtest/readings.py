"""Synthetic readings for the load generators. No locust import, no real patient data.

Values follow the placeholder limits in .env.example (heart rate 50-120, SpO2 >= 92,
temperature 35.5-38.0): mostly normal, about 5% abnormal, about 0.5% at the edge of
the valid range (the app rejects anything beyond it with HTTP 422).
"""

import json
import random
from datetime import datetime

LOG_HEADER = ["device_id", "seq", "send_time_utc", "result", "rtt_ms"]

ABNORMAL_SHARE = 0.05
EXTREME_SHARE = 0.005


def device_id(tag: str, index: int) -> str:
    return f"{tag}-dev-{index:04d}"


def patient_ref(index: int) -> str:
    return f"P{index:04d}"


def utc_stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _vitals(rng: random.Random) -> tuple[int, int, float]:
    heart_rate = rng.randint(60, 100)
    spo2 = rng.randint(95, 100)
    temperature = round(rng.uniform(36.2, 37.4), 1)
    roll = rng.random()
    if roll < EXTREME_SHARE:
        which = rng.choice(["heart_rate", "spo2", "temperature"])
        if which == "heart_rate":
            heart_rate = rng.choice([20, 250])
        elif which == "spo2":
            spo2 = 50
        else:
            temperature = rng.choice([30.0, 45.0])
    elif roll < EXTREME_SHARE + ABNORMAL_SHARE:
        which = rng.choice(["heart_rate", "spo2", "temperature"])
        if which == "heart_rate":
            heart_rate = rng.choice([rng.randint(40, 49), rng.randint(121, 160)])
        elif which == "spo2":
            spo2 = rng.randint(85, 91)
        else:
            temperature = rng.choice(
                [round(rng.uniform(34.5, 35.4), 1), round(rng.uniform(38.1, 39.5), 1)]
            )
    return heart_rate, spo2, temperature


def make_reading(
    rng: random.Random, tag: str, index: int, seq: int, moment: datetime
) -> dict:
    """One reading for device number `index` (1-based) with its own counter `seq`."""
    heart_rate, spo2, temperature = _vitals(rng)
    return {
        "device_id": device_id(tag, index),
        "patient_ref": patient_ref(index),
        "heart_rate": heart_rate,
        "spo2": spo2,
        "temperature": temperature,
        "seq": seq,
        "sent_at": utc_stamp(moment),
    }


def to_json(reading: dict) -> str:
    return json.dumps(reading, separators=(",", ":"))
