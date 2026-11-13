"""SQS inbound adapter (Stage C): a message is deleted only when retrying cannot help.

Stored, duplicate, invalid and unknown-patient readings are deleted; any other error
(for example the database being down) leaves the message in the queue, so SQS delivers
it again after the visibility timeout. A fake client stands in for boto3 (not installed
in the test venv).
"""

from __future__ import annotations

import json
import logging
import sys
from types import SimpleNamespace

import pytest
from conftest import FakeProcess, make_reading, valid_payload

from app import sqs_in
from app.service import UnknownPatient
from app.settings import load_settings

QUEUE_URL = "https://sqs.ap-south-1.amazonaws.com/123456789012/mini-hs-readings"
DB_URL = "postgresql://u:p@localhost/db"


def body(**overrides) -> str:
    return json.dumps(valid_payload(**overrides))


def problems(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


class FakeSqs:
    """Replays scripted receive results. An item is a list of bodies, or an exception."""

    def __init__(self, script=(), delete_failed=()):
        self._script = list(script)
        self._delete_failed = list(delete_failed)
        self.receives: list[dict] = []
        self.deletes: list[dict] = []

    def receive_message(self, **kwargs):
        self.receives.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return {
            "Messages": [
                {"MessageId": f"m{i}", "ReceiptHandle": f"rh{i}", "Body": text}
                for i, text in enumerate(item)
            ]
        }

    def delete_message_batch(self, **kwargs):
        self.deletes.append(kwargs)
        return {"Failed": self._delete_failed} if self._delete_failed else {}

    def deleted_handles(self) -> list[str]:
        return [e["ReceiptHandle"] for call in self.deletes for e in call["Entries"]]


class ProcessFailing:
    """Raises `error` for the given seq numbers, stores everything else."""

    def __init__(self, failing_seqs=(), error=None):
        self.failing = set(failing_seqs)
        self.error = error or RuntimeError("db down")
        self.received: list = []

    def __call__(self, reading):
        self.received.append(reading)
        if reading.seq in self.failing:
            raise self.error
        return "stored"


# ---- handle_body -----------------------------------------------------------


def test_valid_body_calls_process_once_and_is_deletable():
    process = FakeProcess()
    assert sqs_in.handle_body(body(), process) is True
    assert process.received == [make_reading()]


@pytest.mark.parametrize("outcome", ["stored", "duplicate"])
def test_normal_outcomes_are_deletable_and_silent(outcome, caplog):
    caplog.set_level(logging.DEBUG)
    assert sqs_in.handle_body(body(), FakeProcess(outcome=outcome)) is True
    assert problems(caplog) == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "null",
        '{"device_id": ',
        "{}",
        body(heart_rate=19),
        body(spo2=101),
        body(temperature=45.1),
        body(seq=0),
        body(sent_at="yesterday"),
    ],
)
def test_invalid_body_is_logged_deletable_and_process_not_called(text, caplog):
    process = FakeProcess()
    assert sqs_in.handle_body(text, process) is True
    assert process.received == []
    assert problems(caplog)


def test_unknown_patient_is_logged_and_deletable(caplog):
    process = FakeProcess(error=UnknownPatient("P9999"))
    assert sqs_in.handle_body(body(), process) is True
    assert len(process.received) == 1
    assert problems(caplog)


@pytest.mark.parametrize("error", [RuntimeError("db down"), ValueError("boom")])
def test_unexpected_error_is_logged_and_not_deletable(error, caplog):
    process = FakeProcess(error=error)
    assert sqs_in.handle_body(body(), process) is False
    assert len(process.received) == 1
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---- poll_once -------------------------------------------------------------


def test_receive_is_a_long_poll_of_ten_messages():
    client = FakeSqs([[]])
    sqs_in.poll_once(client, QUEUE_URL, FakeProcess())
    assert client.receives == [
        {"QueueUrl": QUEUE_URL, "MaxNumberOfMessages": 10, "WaitTimeSeconds": 20}
    ]


def test_finished_messages_are_deleted_in_one_batch_with_unique_ids():
    client = FakeSqs([[body(seq=1), body(seq=2), body(seq=3)]])
    failed = sqs_in.poll_once(client, QUEUE_URL, FakeProcess())
    assert failed is False
    assert len(client.deletes) == 1
    call = client.deletes[0]
    assert call["QueueUrl"] == QUEUE_URL
    assert call["Entries"] == [
        {"Id": "0", "ReceiptHandle": "rh0"},
        {"Id": "1", "ReceiptHandle": "rh1"},
        {"Id": "2", "ReceiptHandle": "rh2"},
    ]


def test_empty_receive_makes_no_delete_call():
    client = FakeSqs([[]])
    assert sqs_in.poll_once(client, QUEUE_URL, FakeProcess()) is False
    assert client.deletes == []


def test_a_failed_message_stays_in_the_queue_and_does_not_block_the_others():
    client = FakeSqs([[body(seq=1), body(seq=2), body(seq=3)]])
    process = ProcessFailing(failing_seqs={2})
    assert sqs_in.poll_once(client, QUEUE_URL, process) is True
    assert [r.seq for r in process.received] == [1, 2, 3]
    assert client.deleted_handles() == ["rh0", "rh2"]


def test_when_every_message_fails_nothing_is_deleted():
    client = FakeSqs([[body(seq=1), body(seq=2)]])
    process = ProcessFailing(failing_seqs={1, 2})
    assert sqs_in.poll_once(client, QUEUE_URL, process) is True
    assert client.deletes == []


def test_invalid_and_valid_messages_in_one_batch_are_all_deleted():
    client = FakeSqs([["not json", body(seq=2)]])
    process = FakeProcess()
    assert sqs_in.poll_once(client, QUEUE_URL, process) is False
    assert len(process.received) == 1
    assert client.deleted_handles() == ["rh0", "rh1"]


def test_a_failed_delete_entry_is_logged_not_raised(caplog):
    failed = [{"Id": "0", "Code": "ReceiptHandleIsInvalid", "SenderFault": True}]
    client = FakeSqs([[body()]], delete_failed=failed)
    assert sqs_in.poll_once(client, QUEUE_URL, FakeProcess()) is False
    assert problems(caplog)


def test_aws_errors_from_receive_propagate_to_the_caller():
    client = FakeSqs([RuntimeError("AccessDenied")])
    with pytest.raises(RuntimeError, match="AccessDenied"):
        sqs_in.poll_once(client, QUEUE_URL, FakeProcess())


# ---- run -------------------------------------------------------------------


@pytest.fixture
def settings():
    return load_settings(
        {"DATABASE_URL": DB_URL, "INPUT_MODE": "sqs", "SQS_QUEUE_URL": QUEUE_URL}
    )


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    calls: list[float] = []
    monkeypatch.setattr(sqs_in.time, "sleep", calls.append)
    return calls


def test_run_uses_the_configured_queue_url(settings, sleeps):
    client = FakeSqs([[], KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        sqs_in.run(settings, FakeProcess(), client=client)
    assert {r["QueueUrl"] for r in client.receives} == {QUEUE_URL}


def test_run_survives_an_aws_error_pauses_and_goes_on(settings, sleeps, caplog):
    client = FakeSqs([RuntimeError("AccessDenied"), [body()], KeyboardInterrupt()])
    process = FakeProcess()
    with pytest.raises(KeyboardInterrupt):
        sqs_in.run(settings, process, client=client)
    assert len(process.received) == 1
    assert client.deleted_handles() == ["rh0"]
    assert sleeps == [sqs_in.ERROR_PAUSE_S]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_run_pauses_after_a_batch_with_an_unexpected_failure(settings, sleeps):
    client = FakeSqs([[body(seq=1)], KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        sqs_in.run(settings, ProcessFailing(failing_seqs={1}), client=client)
    assert sleeps == [sqs_in.ERROR_PAUSE_S]


def test_run_does_not_pause_when_everything_succeeds(settings, sleeps):
    client = FakeSqs([[body(seq=1)], [], KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        sqs_in.run(settings, FakeProcess(), client=client)
    assert sleeps == []


def test_run_builds_a_boto3_sqs_client_when_none_is_given(
    settings, sleeps, monkeypatch
):
    client = FakeSqs([KeyboardInterrupt()])
    requested: list[str] = []

    def fake_client(service):
        requested.append(service)
        return client

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_client))
    with pytest.raises(KeyboardInterrupt):
        sqs_in.run(settings, FakeProcess())
    assert requested == ["sqs"]


# ---- main(["worker"]) picks the input from INPUT_MODE ------------------------


@pytest.fixture
def worker_calls(monkeypatch) -> list[tuple[str, object]]:
    from app import main, mqtt_in

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(main, "_wire", lambda settings: (None, "the-processor"))
    monkeypatch.setattr(mqtt_in, "run", lambda s, p: calls.append(("mqtt", p)))
    monkeypatch.setattr(sqs_in, "run", lambda s, p: calls.append(("sqs", p)))
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.delenv("INPUT_MODE", raising=False)
    monkeypatch.delenv("SQS_QUEUE_URL", raising=False)
    return calls


def test_worker_reads_from_mqtt_by_default(worker_calls):
    from app.main import main

    assert main(["worker"]) == 0
    assert worker_calls == [("mqtt", "the-processor")]


def test_worker_reads_from_sqs_when_asked(worker_calls, monkeypatch):
    from app.main import main

    monkeypatch.setenv("INPUT_MODE", "sqs")
    monkeypatch.setenv("SQS_QUEUE_URL", QUEUE_URL)
    assert main(["worker"]) == 0
    assert worker_calls == [("sqs", "the-processor")]


def test_worker_refuses_to_start_in_sqs_mode_without_a_queue_url(
    worker_calls, monkeypatch
):
    from app.main import main

    monkeypatch.setenv("INPUT_MODE", "sqs")
    with pytest.raises(ValueError, match="SQS_QUEUE_URL"):
        main(["worker"])
    assert worker_calls == []
