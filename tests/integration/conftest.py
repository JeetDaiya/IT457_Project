"""Fixtures for tests that need the running stack (Compose on a laptop or the EC2 VM).

Point them at a stack with:
  TEST_BASE_URL=http://localhost:8000
  TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/db
  TEST_MQTT_HOST=localhost        (TEST_MQTT_PORT defaults to 1883)
Anything unset -> every integration test is skipped, so plain `pytest` stays fast.
"""

from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

PREFIX = "it-"
RUN_TAG = PREFIX + uuid.uuid4().hex[:8]


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} not set; integration tests need a running stack")
    return value


@pytest.fixture(scope="session")
def base_url() -> str:
    return _required("TEST_BASE_URL").rstrip("/")


@pytest.fixture(scope="session")
def mqtt_target() -> tuple[str, int]:
    return _required("TEST_MQTT_HOST"), int(os.environ.get("TEST_MQTT_PORT", "1883"))


@pytest.fixture(scope="session")
def db():
    # psycopg2 wants a plain libpq URL, so drop SQLAlchemy's "+psycopg2" if it was pasted in.
    url = _required("TEST_DATABASE_URL").replace("+psycopg2", "", 1)
    conn = psycopg2.connect(url)
    conn.autocommit = True
    yield conn
    with conn.cursor() as cur:  # remove only rows this run created
        cur.execute("DELETE FROM readings WHERE device_id LIKE %s", (RUN_TAG + "-%",))
    conn.close()


@pytest.fixture
def device_id(request) -> str:
    """A device id unique to this test, so reruns never hit UNIQUE (device_id, seq)."""
    return f"{RUN_TAG}-{request.node.name}"[:100].replace("[", "_").replace("]", "")
