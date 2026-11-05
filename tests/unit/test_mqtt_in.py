"""MQTT inbound adapter: handle_message never raises; run() wires the client."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import ClassVar

import pytest
from conftest import FakeProcess, make_reading, valid_payload

from app import mqtt_in
from app.service import UnknownPatient
from app.settings import load_settings

DB_URL = "postgresql://u:p@localhost/db"


def encode(**overrides) -> bytes:
    return json.dumps(valid_payload(**overrides)).encode()


def problems(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


# ---- handle_message --------------------------------------------------------


def test_valid_payload_calls_process_once_with_the_reading():
    process = FakeProcess()
    mqtt_in.handle_message(encode(), process)
    assert process.received == [make_reading()]


@pytest.mark.parametrize("outcome", ["stored", "duplicate"])
def test_normal_outcomes_are_silent(outcome, caplog):
    caplog.set_level(logging.DEBUG)
    mqtt_in.handle_message(encode(), FakeProcess(outcome=outcome))
    assert problems(caplog) == []


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not json",
        b"\xff\xfe\x00garbage",
        b"[]",
        b"null",
        b'{"device_id": ',
        json.dumps({}).encode(),
        encode(heart_rate=19),
        encode(heart_rate=251),
        encode(spo2=49),
        encode(spo2=101),
        encode(temperature=29.9),
        encode(temperature=45.1),
        encode(heart_rate="fast"),
        encode(seq=0),
        encode(sent_at="yesterday"),
        encode(device_id=""),
    ],
)
def test_invalid_payload_is_logged_and_process_not_called(payload, caplog):
    process = FakeProcess()
    mqtt_in.handle_message(payload, process)
    assert process.received == []
    assert problems(caplog)


@pytest.mark.parametrize(
    "missing",
    ["device_id", "patient_ref", "heart_rate", "spo2", "temperature", "seq", "sent_at"],
)
def test_missing_field_is_logged_and_process_not_called(missing, caplog):
    body = valid_payload()
    del body[missing]
    process = FakeProcess()
    mqtt_in.handle_message(json.dumps(body).encode(), process)
    assert process.received == []
    assert problems(caplog)


@pytest.mark.parametrize(
    "error",
    [UnknownPatient("P9999"), RuntimeError("db down"), ValueError("boom")],
)
def test_process_errors_are_logged_and_swallowed(error, caplog):
    process = FakeProcess(error=error)
    mqtt_in.handle_message(encode(), process)
    assert len(process.received) == 1
    assert problems(caplog)


# ---- run() with a fake client ---------------------------------------------


class FakeClient:
    instances: ClassVar[list[FakeClient]] = []

    def __init__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        self.calls: list[tuple[str, tuple, dict]] = []
        FakeClient.instances.append(self)

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def reconnect_delay_set(self, *args, **kwargs):
        self._record("reconnect_delay_set", *args, **kwargs)

    def connect_async(self, *args, **kwargs):
        self._record("connect_async", *args, **kwargs)

    def connect(self, *args, **kwargs):
        self._record("connect", *args, **kwargs)

    def loop_forever(self, *args, **kwargs):
        self._record("loop_forever", *args, **kwargs)

    def subscribe(self, *args, **kwargs):
        self._record("subscribe", *args, **kwargs)

    def named(self, name):
        return [(a, k) for n, a, k in self.calls if n == name]


@pytest.fixture
def client(monkeypatch) -> FakeClient:
    FakeClient.instances = []
    monkeypatch.setattr(mqtt_in.mqtt, "Client", FakeClient)
    return FakeClient


def run_default(process=None) -> FakeClient:
    settings = load_settings({"DATABASE_URL": DB_URL})
    mqtt_in.run(settings, process or FakeProcess())
    assert len(FakeClient.instances) == 1
    return FakeClient.instances[0]


def test_constants():
    assert mqtt_in.CLIENT_ID == "healthsuite-worker"
    assert mqtt_in.QOS == 1


def test_client_is_created_with_persistent_session(client):
    fake = run_default()
    assert fake.init_kwargs == {
        "client_id": "healthsuite-worker",
        "clean_session": False,
    }


def test_callbacks_are_installed(client):
    fake = run_default()
    assert callable(fake.on_connect)
    assert callable(fake.on_message)


def test_reconnect_delay_is_set(client):
    fake = run_default()
    ((args, kwargs),) = fake.named("reconnect_delay_set")
    assert args == () and kwargs == {"min_delay": 1, "max_delay": 30}


def test_connects_asynchronously_to_default_host_and_port(client):
    fake = run_default()
    assert fake.named("connect") == []
    ((args, kwargs),) = fake.named("connect_async")
    assert (args, kwargs) == (("localhost", 1883), {})
    assert isinstance(args[1], int)


def test_loop_forever_retries_first_connection(client):
    fake = run_default()
    ((args, kwargs),) = fake.named("loop_forever")
    assert args == () and kwargs == {"retry_first_connection": True}


def test_call_order(client):
    fake = run_default()
    assert [n for n, _, _ in fake.calls] == [
        "reconnect_delay_set",
        "connect_async",
        "loop_forever",
    ]


def test_custom_host_port_and_topic_are_passed_through(client):
    settings = load_settings(
        {
            "DATABASE_URL": DB_URL,
            "MQTT_HOST": "broker.internal",
            "MQTT_PORT": "8883",
            "MQTT_TOPIC": "devices/+/vitals",
        }
    )
    mqtt_in.run(settings, FakeProcess())
    fake = FakeClient.instances[0]
    ((args, _),) = fake.named("connect_async")
    assert args == ("broker.internal", 8883)
    assert isinstance(args[1], int)
    fake.on_connect(fake, None, {}, 0)
    ((sub_args, sub_kwargs),) = fake.named("subscribe")
    assert sub_args == ("devices/+/vitals",)
    assert sub_kwargs == {"qos": 1}


# ---- on_connect ------------------------------------------------------------


def test_successful_connect_subscribes_with_qos_1(client):
    fake = run_default()
    fake.on_connect(fake, None, {}, 0)
    assert fake.named("subscribe") == [(("vitals/#",), {"qos": 1})]


def test_subscribes_again_on_every_reconnect(client):
    fake = run_default()
    for _ in range(3):
        fake.on_connect(fake, None, {}, 0)
    assert len(fake.named("subscribe")) == 3


@pytest.mark.parametrize("rc", [1, 2, 3, 4, 5])
def test_failed_connect_logs_error_and_does_not_subscribe(client, rc, caplog):
    fake = run_default()
    fake.on_connect(fake, None, {}, rc)
    assert fake.named("subscribe") == []
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_subscribe_resumes_after_failed_then_successful_connect(client):
    fake = run_default()
    fake.on_connect(fake, None, {}, 5)
    fake.on_connect(fake, None, {}, 0)
    assert len(fake.named("subscribe")) == 1


# ---- on_message ------------------------------------------------------------


def test_message_callback_passes_parsed_reading_to_process(client):
    process = FakeProcess()
    fake = run_default(process)
    fake.on_message(fake, None, SimpleNamespace(payload=encode()))
    assert process.received == [make_reading()]


def test_message_callback_with_garbage_does_not_raise(client, caplog):
    process = FakeProcess()
    fake = run_default(process)
    fake.on_message(fake, None, SimpleNamespace(payload=b"\x00garbage{"))
    assert process.received == []
    assert problems(caplog)


def test_message_callback_swallows_process_errors(client):
    process = FakeProcess(error=RuntimeError("db down"))
    fake = run_default(process)
    fake.on_message(fake, None, SimpleNamespace(payload=encode()))
    assert len(process.received) == 1
