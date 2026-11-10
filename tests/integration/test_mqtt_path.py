"""MQTT broker -> worker -> process_reading -> real PostgreSQL (Stages A and B).

Stage C feeds the worker from an SQS queue instead, so this is the one file that gets
an SQS counterpart there; the HTTP tests stay as they are.
"""

from __future__ import annotations

import pytest

from integration.live import fetch_rows, mqtt_publish, payload, wait_for_stored

pytestmark = pytest.mark.integration


def test_published_reading_is_stored(mqtt_target, db, device_id):
    mqtt_publish(*mqtt_target, payload(device_id))
    (row,) = wait_for_stored(db, device_id)
    assert row["received_at"] <= row["stored_at"]


def test_redelivered_reading_is_stored_once(mqtt_target, db, device_id):
    mqtt_publish(*mqtt_target, payload(device_id), times=2)
    assert len(wait_for_stored(db, device_id)) == 1
    assert len(fetch_rows(db, device_id)) == 1
