"""Helpers for the integration tests. These talk to a *running* stack and know nothing
about how it was deployed (laptop, EC2 VM, RDS); only the TEST_* env vars differ."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import paho.mqtt.client as mqtt

POLL_S = 0.1


def payload(device_id: str, seq: int = 1, **overrides: Any) -> dict[str, Any]:
    """One valid, all-normal reading for a seeded patient."""
    reading: dict[str, Any] = {
        "device_id": device_id,
        "patient_ref": "P0007",
        "heart_rate": 72,
        "spo2": 97,
        "temperature": 36.8,
        "seq": seq,
        "sent_at": "2026-11-05T09:15:03.412Z",
    }
    reading.update(overrides)
    return reading


def post(base_url: str, reading: dict[str, Any]) -> httpx.Response:
    return httpx.post(f"{base_url}/readings", json=reading, timeout=5)


def fetch_rows(db, device_id: str) -> list[dict[str, Any]]:
    with db.cursor() as cur:
        cur.execute(
            "SELECT device_id, seq, abnormal, received_at, stored_at "
            "FROM readings WHERE device_id = %s ORDER BY seq",
            (device_id,),
        )
        names = [col.name for col in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def wait_for_stored(db, device_id: str, count: int = 1, timeout: float = 5) -> list:
    """Poll until `count` rows for the device have `stored_at` set (it is set by a second
    UPDATE, so it can lag the insert). Returns the rows seen at the deadline."""
    deadline = time.monotonic() + timeout
    while True:
        rows = [r for r in fetch_rows(db, device_id) if r["stored_at"] is not None]
        if len(rows) >= count or time.monotonic() >= deadline:
            return rows
        time.sleep(POLL_S)


def lost_readings(db, device_id: str) -> int:
    """The measurement formula from CLAUDE.md: (max(seq)-min(seq)+1) - count(distinct seq)."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT (max(seq) - min(seq) + 1) - count(DISTINCT seq) "
            "FROM readings WHERE device_id = %s",
            (device_id,),
        )
        return int(cur.fetchone()[0])


def mqtt_publish(host: str, port: int, reading: dict[str, Any], times: int = 1) -> None:
    """Publish the reading at QoS 1 on vitals/<device_id> and wait for each PUBACK."""
    client = mqtt.Client()
    client.connect(host, port)
    client.loop_start()
    try:
        for _ in range(times):
            info = client.publish(
                f"vitals/{reading['device_id']}", json.dumps(reading), qos=1
            )
            info.wait_for_publish(timeout=5)
            if not info.is_published():
                raise TimeoutError("no PUBACK from the broker within 5 s")
    finally:
        client.loop_stop()
        client.disconnect()
