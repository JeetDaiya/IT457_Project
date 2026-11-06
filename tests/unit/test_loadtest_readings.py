"""Load-generator readings: every message must be accepted by the app's own rules."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime

from conftest import DEFAULT_LIMITS

from app.rules import Reading, is_abnormal
from loadtest.readings import LOG_HEADER, make_reading, to_json

NOW = datetime(2026, 11, 5, 9, 15, 3, 412000, tzinfo=UTC)
TAG = "ah100r2"


def _readings(count: int, seed: int = 1) -> list[dict]:
    rng = random.Random(seed)
    return [
        make_reading(rng, TAG, 1 + n % 100, 1 + n // 100, NOW) for n in range(count)
    ]


def test_every_reading_passes_the_app_validation():
    for reading in _readings(20000):
        Reading.model_validate(reading)


def test_message_is_the_seven_fields_and_small():
    text = to_json(make_reading(random.Random(1), TAG, 7, 1042, NOW))
    assert len(text.encode()) < 200
    assert list(json.loads(text)) == [
        "device_id",
        "patient_ref",
        "heart_rate",
        "spo2",
        "temperature",
        "seq",
        "sent_at",
    ]


def test_ids_sent_at_and_types():
    reading = make_reading(random.Random(1), TAG, 7, 1042, NOW)
    assert reading["device_id"] == "ah100r2-dev-0007"
    assert reading["patient_ref"] == "P0007"
    assert reading["seq"] == 1042
    assert reading["sent_at"] == "2026-11-05T09:15:03.412Z"
    assert isinstance(reading["heart_rate"], int)
    assert isinstance(reading["spo2"], int)
    assert isinstance(reading["temperature"], float)


def test_mix_is_mostly_normal_with_some_abnormal_and_a_few_extremes():
    readings = _readings(20000)
    models = [Reading.model_validate(r) for r in readings]
    abnormal = sum(is_abnormal(m, DEFAULT_LIMITS) for m in models)
    assert 0.03 * len(models) < abnormal < 0.08 * len(models)
    extremes = sum(
        m.heart_rate in (20, 250) or m.spo2 == 50 or m.temperature in (30.0, 45.0)
        for m in models
    )
    assert 0 < extremes < 0.01 * len(models)


def test_same_seed_gives_same_readings():
    assert _readings(500, seed=3) == _readings(500, seed=3)


def test_log_header_is_the_shared_format():
    assert LOG_HEADER == ["device_id", "seq", "send_time_utc", "result", "rtt_ms"]
