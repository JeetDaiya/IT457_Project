"""Settings loading from an env mapping (never from os.environ directly)."""

from __future__ import annotations

import dataclasses

import pytest

from app.rules import Limits
from app.settings import Settings, load_settings

DB_URL = "postgresql+psycopg2://user:secret@localhost:5432/minihs"


def env(**extra: str) -> dict[str, str]:
    return {"DATABASE_URL": DB_URL, **extra}


# ---- defaults --------------------------------------------------------------


def test_load_settings_returns_settings_instance():
    assert isinstance(load_settings(env()), Settings)


def test_database_url_is_taken_from_env():
    assert load_settings(env()).database_url == DB_URL


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("mqtt_host", "localhost"),
        ("mqtt_port", 1883),
        ("mqtt_topic", "vitals/#"),
        ("heart_rate_min", 50),
        ("heart_rate_max", 120),
        ("spo2_min", 92),
        ("temperature_min", 35.5),
        ("temperature_max", 38.0),
        ("seed_patients", 100),
        ("log_level", "INFO"),
    ],
)
def test_defaults_when_only_database_url_is_given(attribute, expected):
    assert getattr(load_settings(env()), attribute) == expected


# ---- overrides -------------------------------------------------------------


def test_every_value_can_be_overridden():
    settings = load_settings(
        env(
            MQTT_HOST="broker.internal",
            MQTT_PORT="8883",
            MQTT_TOPIC="devices/#",
            HEART_RATE_MIN="55",
            HEART_RATE_MAX="110",
            SPO2_MIN="94",
            TEMPERATURE_MIN="36.0",
            TEMPERATURE_MAX="37.5",
            SEED_PATIENTS="20",
            LOG_LEVEL="DEBUG",
        )
    )
    assert settings.mqtt_host == "broker.internal"
    assert settings.mqtt_port == 8883
    assert settings.mqtt_topic == "devices/#"
    assert settings.heart_rate_min == 55
    assert settings.heart_rate_max == 110
    assert settings.spo2_min == 94
    assert settings.temperature_min == 36.0
    assert settings.temperature_max == 37.5
    assert settings.seed_patients == 20
    assert settings.log_level == "DEBUG"


def test_numeric_values_are_converted_to_numbers_not_left_as_strings():
    settings = load_settings(
        env(
            MQTT_PORT="1884",
            HEART_RATE_MIN="45",
            TEMPERATURE_MAX="38.5",
            SEED_PATIENTS="7",
        )
    )
    assert isinstance(settings.mqtt_port, int)
    assert isinstance(settings.heart_rate_min, int)
    assert isinstance(settings.seed_patients, int)
    assert isinstance(settings.temperature_max, float)


def test_unrelated_env_variables_are_ignored():
    settings = load_settings(env(PATH="/usr/bin", HOME="/home/x"))
    assert settings.database_url == DB_URL


# ---- DATABASE_URL is required ---------------------------------------------


def test_missing_database_url_raises_value_error():
    with pytest.raises(ValueError):
        load_settings({})


def test_empty_database_url_raises_value_error():
    with pytest.raises(ValueError):
        load_settings({"DATABASE_URL": ""})


def test_missing_database_url_raises_even_if_other_values_are_set():
    with pytest.raises(ValueError):
        load_settings({"MQTT_HOST": "broker", "SEED_PATIENTS": "5"})


# ---- bad numbers -----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "MQTT_PORT",
        "HEART_RATE_MIN",
        "HEART_RATE_MAX",
        "SPO2_MIN",
        "TEMPERATURE_MIN",
        "TEMPERATURE_MAX",
        "SEED_PATIENTS",
    ],
)
def test_non_numeric_value_raises_value_error(name):
    with pytest.raises(ValueError):
        load_settings(env(**{name: "abc"}))


# ---- immutability ----------------------------------------------------------


def test_settings_are_immutable():
    settings = load_settings(env())
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.log_level = "DEBUG"  # type: ignore[misc]


# ---- limits() mapping ------------------------------------------------------


def test_limits_maps_defaults_to_a_limits_object():
    assert load_settings(env()).limits() == Limits(
        heart_rate_min=50,
        heart_rate_max=120,
        spo2_min=92,
        temperature_min=35.5,
        temperature_max=38.0,
    )


def test_limits_reflects_overridden_values():
    settings = load_settings(
        env(
            HEART_RATE_MIN="60",
            HEART_RATE_MAX="100",
            SPO2_MIN="95",
            TEMPERATURE_MIN="36.0",
            TEMPERATURE_MAX="37.5",
        )
    )
    assert settings.limits() == Limits(
        heart_rate_min=60,
        heart_rate_max=100,
        spo2_min=95,
        temperature_min=36.0,
        temperature_max=37.5,
    )
