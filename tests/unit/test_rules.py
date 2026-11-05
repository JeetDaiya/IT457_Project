"""Domain rules: Reading validity ranges and is_abnormal()."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import DEFAULT_LIMITS, READING_FIELDS, make_reading, valid_payload
from pydantic import ValidationError

from app.rules import Limits, Reading, is_abnormal

# --------------------------------------------------------------------------
# Reading: hard validity ranges (inclusive bounds are valid)
# --------------------------------------------------------------------------

VALID_BOUNDARIES = [
    ("heart_rate", 20),
    ("heart_rate", 250),
    ("spo2", 50),
    ("spo2", 100),
    ("temperature", 30.0),
    ("temperature", 45.0),
]

INVALID_BOUNDARIES = [
    ("heart_rate", 19),
    ("heart_rate", 251),
    ("spo2", 49),
    ("spo2", 101),
    ("temperature", 29.9),
    ("temperature", 45.1),
]


@pytest.mark.parametrize(("field", "value"), VALID_BOUNDARIES)
def test_reading_accepts_value_on_inclusive_bound(field, value):
    reading = make_reading(**{field: value})
    assert getattr(reading, field) == value


@pytest.mark.parametrize(("field", "value"), INVALID_BOUNDARIES)
def test_reading_rejects_value_just_outside_range(field, value):
    with pytest.raises(ValidationError):
        make_reading(**{field: value})


def test_reading_accepts_a_typical_valid_payload():
    reading = Reading(**valid_payload())
    assert reading.device_id == "dev-0007"
    assert reading.patient_ref == "P0007"
    assert reading.seq == 1042


@pytest.mark.parametrize("field", READING_FIELDS)
def test_reading_rejects_missing_field(field):
    payload = valid_payload()
    del payload[field]
    with pytest.raises(ValidationError):
        Reading(**payload)


@pytest.mark.parametrize("bad_seq", [0, -1])
def test_reading_rejects_seq_below_one(bad_seq):
    with pytest.raises(ValidationError):
        make_reading(seq=bad_seq)


def test_reading_accepts_seq_of_one():
    assert make_reading(seq=1).seq == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("heart_rate", "fast"),
        ("spo2", "high"),
        ("temperature", "warm"),
        ("seq", "first"),
    ],
)
def test_reading_rejects_non_numeric_values(field, value):
    with pytest.raises(ValidationError):
        make_reading(**{field: value})


def test_reading_rejects_unparseable_sent_at():
    with pytest.raises(ValidationError):
        make_reading(sent_at="not-a-timestamp")


# --------------------------------------------------------------------------
# Reading: immutability and sent_at parsing
# --------------------------------------------------------------------------


def test_reading_is_immutable():
    reading = make_reading()
    with pytest.raises(ValidationError):
        reading.heart_rate = 80


def test_sent_at_with_trailing_z_parses_to_aware_utc_datetime():
    reading = make_reading(sent_at="2026-11-05T09:15:03.412Z")
    assert isinstance(reading.sent_at, datetime)
    assert reading.sent_at.tzinfo is not None
    assert reading.sent_at.utcoffset() == timedelta(0)
    assert reading.sent_at == datetime(2026, 11, 5, 9, 15, 3, 412_000, tzinfo=UTC)


def test_sent_at_with_explicit_utc_offset_parses_to_same_instant():
    z_form = make_reading(sent_at="2026-11-05T09:15:03.412Z")
    offset_form = make_reading(sent_at="2026-11-05T09:15:03.412+00:00")
    assert offset_form.sent_at == z_form.sent_at
    assert offset_form.sent_at.tzinfo is not None


# --------------------------------------------------------------------------
# is_abnormal: default limits HR 50-120, SpO2 >= 92, temp 35.5-38.0
# --------------------------------------------------------------------------


def test_all_normal_reading_is_not_abnormal():
    assert is_abnormal(make_reading(), DEFAULT_LIMITS) is False


@pytest.mark.parametrize(
    ("heart_rate", "expected"),
    [(49, True), (50, False), (120, False), (121, True)],
)
def test_heart_rate_boundaries(heart_rate, expected):
    assert is_abnormal(make_reading(heart_rate=heart_rate), DEFAULT_LIMITS) is expected


@pytest.mark.parametrize(
    ("spo2", "expected"),
    [(91, True), (92, False), (100, False)],
)
def test_spo2_boundaries(spo2, expected):
    assert is_abnormal(make_reading(spo2=spo2), DEFAULT_LIMITS) is expected


@pytest.mark.parametrize(
    ("temperature", "expected"),
    [(35.4, True), (35.5, False), (38.0, False), (38.1, True)],
)
def test_temperature_boundaries(temperature, expected):
    reading = make_reading(temperature=temperature)
    assert is_abnormal(reading, DEFAULT_LIMITS) is expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"heart_rate": 130},
        {"heart_rate": 40},
        {"spo2": 85},
        {"temperature": 39.5},
        {"temperature": 34.0},
    ],
)
def test_any_single_out_of_limit_value_makes_reading_abnormal(overrides):
    assert is_abnormal(make_reading(**overrides), DEFAULT_LIMITS) is True


def test_several_out_of_limit_values_are_abnormal():
    reading = make_reading(heart_rate=140, spo2=80, temperature=40.0)
    assert is_abnormal(reading, DEFAULT_LIMITS) is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"heart_rate": 20},
        {"heart_rate": 250},
        {"spo2": 50},
        {"temperature": 30.0},
        {"temperature": 45.0},
    ],
)
def test_extreme_but_valid_values_are_abnormal(overrides):
    assert is_abnormal(make_reading(**overrides), DEFAULT_LIMITS) is True


# --------------------------------------------------------------------------
# is_abnormal: custom limits are respected, not hard-coded
# --------------------------------------------------------------------------

STRICT_LIMITS = Limits(
    heart_rate_min=60,
    heart_rate_max=100,
    spo2_min=95,
    temperature_min=36.0,
    temperature_max=37.5,
)


@pytest.mark.parametrize(
    ("overrides", "abnormal_under_strict"),
    [
        ({"heart_rate": 55}, True),
        ({"heart_rate": 60}, False),
        ({"heart_rate": 100}, False),
        ({"heart_rate": 110}, True),
        ({"spo2": 94}, True),
        ({"spo2": 95}, False),
        ({"temperature": 35.9}, True),
        ({"temperature": 36.0}, False),
        ({"temperature": 37.5}, False),
        ({"temperature": 37.6}, True),
    ],
)
def test_custom_limits_are_respected(overrides, abnormal_under_strict):
    reading = make_reading(**overrides)
    assert is_abnormal(reading, STRICT_LIMITS) is abnormal_under_strict


def test_same_reading_can_be_normal_under_default_and_abnormal_under_strict_limits():
    reading = make_reading(heart_rate=55)
    assert is_abnormal(reading, DEFAULT_LIMITS) is False
    assert is_abnormal(reading, STRICT_LIMITS) is True


def test_limits_are_immutable():
    with pytest.raises(AttributeError):
        DEFAULT_LIMITS.heart_rate_min = 10  # type: ignore[misc]
