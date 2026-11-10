"""HTTP -> process_reading -> real PostgreSQL, against a running stack."""

from __future__ import annotations

import httpx
import pytest

from integration.live import fetch_rows, lost_readings, payload, post, wait_for_stored

pytestmark = pytest.mark.integration


def test_valid_reading_is_stored_with_timestamps(base_url, db, device_id):
    assert post(base_url, payload(device_id)).status_code == 201
    (row,) = wait_for_stored(db, device_id)
    assert row["abnormal"] is False
    assert row["received_at"] <= row["stored_at"]


def test_abnormal_reading_is_flagged(base_url, db, device_id):
    assert post(base_url, payload(device_id, heart_rate=130)).status_code == 201
    (row,) = wait_for_stored(db, device_id)
    assert row["abnormal"] is True


def test_duplicate_is_200_and_stored_once(base_url, db, device_id):
    reading = payload(device_id)
    assert post(base_url, reading).status_code == 201
    assert post(base_url, reading).status_code == 200
    assert len(wait_for_stored(db, device_id)) == 1
    assert len(fetch_rows(db, device_id)) == 1


@pytest.mark.parametrize(
    ("field", "value"), [("heart_rate", 19), ("spo2", 101), ("temperature", 45.1)]
)
def test_out_of_range_is_422_and_not_stored(base_url, db, device_id, field, value):
    response = post(base_url, payload(device_id, **{field: value}))
    assert response.status_code == 422
    assert fetch_rows(db, device_id) == []


def test_unknown_patient_is_422_and_not_stored(base_url, db, device_id):
    response = post(base_url, payload(device_id, patient_ref="P9999"))
    assert response.status_code == 422
    assert fetch_rows(db, device_id) == []


def test_lost_readings_query_counts_zero_then_one(base_url, db, device_id):
    for seq in range(1, 21):
        assert post(base_url, payload(device_id, seq)).status_code == 201
    assert lost_readings(db, device_id) == 0

    gappy = f"{device_id}-gap"
    for seq in [s for s in range(1, 21) if s != 7]:
        assert post(base_url, payload(gappy, seq)).status_code == 201
    assert lost_readings(db, gappy) == 1


def test_health_stats_and_latest(base_url, db, device_id):
    assert post(base_url, payload(device_id)).status_code == 201
    wait_for_stored(db, device_id)
    assert httpx.get(f"{base_url}/health", timeout=5).status_code == 200
    assert httpx.get(f"{base_url}/stats", timeout=5).json()["total"] >= 1
    latest = httpx.get(f"{base_url}/readings/latest?limit=500", timeout=5).json()
    assert device_id in {row["device_id"] for row in latest}
