"""SQS queue -> worker -> process_reading -> real PostgreSQL (Stage C).

The test sends straight to the queue, so it checks our code (the SQS input, the processor
and RDS) and leaves IoT Core, its rule and TLS to test_iot_path.py. If this file passes and
that one fails, the problem is in front of the queue.
"""

from __future__ import annotations

import pytest

from integration.live import (
    fetch_rows,
    payload,
    sqs_send,
    wait_for_queue_empty,
    wait_for_stored,
)

pytestmark = pytest.mark.integration

SQS_WAIT_S = 15  # long poll and the queue hop add time the MQTT path does not have


def test_queued_reading_is_stored(sqs_target, db, device_id):
    sqs_send(sqs_target, payload(device_id))
    (row,) = wait_for_stored(db, device_id, timeout=SQS_WAIT_S)
    assert row["received_at"] <= row["stored_at"]


def test_redelivered_reading_is_stored_once(sqs_target, db, device_id):
    sqs_send(sqs_target, payload(device_id), times=2)
    assert len(wait_for_stored(db, device_id, timeout=SQS_WAIT_S)) == 1
    # The first row appears before the second copy is consumed, so wait for the queue to
    # drain; otherwise "one row" could simply mean the duplicate has not arrived yet.
    assert wait_for_queue_empty(sqs_target), (
        "queue not empty after 15 s: purge leftover messages before running the tests"
    )
    assert len(fetch_rows(db, device_id)) == 1
