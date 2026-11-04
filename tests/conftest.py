"""Shared fakes and factories. Written from the specification only.

No __init__.py files exist under tests/, so pytest puts this directory on
sys.path and test modules can do `from conftest import ...`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.service import Limits, Reading, UnknownPatient

# Two distinct, ordered instants for scripted clocks.
T1 = datetime(2026, 11, 5, 9, 15, 3, 500_000, tzinfo=UTC)
T2 = datetime(2026, 11, 5, 9, 15, 3, 520_000, tzinfo=UTC)
T3 = datetime(2026, 11, 5, 9, 15, 4, 100_000, tzinfo=UTC)
T4 = datetime(2026, 11, 5, 9, 15, 4, 130_000, tzinfo=UTC)

DEFAULT_LIMITS = Limits(
    heart_rate_min=50,
    heart_rate_max=120,
    spo2_min=92,
    temperature_min=35.5,
    temperature_max=38.0,
)

READING_FIELDS = (
    "device_id",
    "patient_ref",
    "heart_rate",
    "spo2",
    "temperature",
    "seq",
    "sent_at",
)


def valid_payload(**overrides: Any) -> dict[str, Any]:
    """A JSON-ready dict for one valid, all-normal reading."""
    payload: dict[str, Any] = {
        "device_id": "dev-0007",
        "patient_ref": "P0007",
        "heart_rate": 72,
        "spo2": 97,
        "temperature": 36.8,
        "seq": 1042,
        "sent_at": "2026-11-05T09:15:03.412Z",
    }
    payload.update(overrides)
    return payload


def make_reading(**overrides: Any) -> Reading:
    """A valid Reading; override any field by keyword."""
    return Reading(**valid_payload(**overrides))


class FakeClock:
    """Returns a scripted sequence of datetimes and counts calls."""

    def __init__(self, times: list[datetime], events: list[str] | None = None):
        self._times = list(times)
        self.calls = 0
        self._events = events

    def now(self) -> datetime:
        if self.calls >= len(self._times):
            raise AssertionError("FakeClock script exhausted: now() called too often")
        value = self._times[self.calls]
        self.calls += 1
        if self._events is not None:
            self._events.append("now")
        return value


class InMemoryStore:
    """In-memory ReadingStore. Rows keyed by (device_id, seq)."""

    def __init__(
        self,
        known_patients: set[str] | None = None,
        events: list[str] | None = None,
    ):
        self.known_patients = (
            {"P0007"} if known_patients is None else set(known_patients)
        )
        self.rows: dict[tuple[str, int], dict[str, Any]] = {}
        self.add_calls: list[dict[str, Any]] = []
        self.mark_calls: list[tuple[int, datetime]] = []
        self._next_id = 1
        self._events = events

    def add(
        self, reading: Reading, abnormal: bool, received_at: datetime
    ) -> int | None:
        self.add_calls.append(
            {"reading": reading, "abnormal": abnormal, "received_at": received_at}
        )
        if self._events is not None:
            self._events.append("add")
        if reading.patient_ref not in self.known_patients:
            raise UnknownPatient(reading.patient_ref)
        key = (reading.device_id, reading.seq)
        if key in self.rows:
            return None
        row_id = self._next_id
        self._next_id += 1
        self.rows[key] = {
            "id": row_id,
            "reading": reading,
            "abnormal": abnormal,
            "received_at": received_at,
            "stored_at": None,
        }
        return row_id

    def mark_stored(self, row_id: int, stored_at: datetime) -> None:
        self.mark_calls.append((row_id, stored_at))
        if self._events is not None:
            self._events.append("mark_stored")
        for row in self.rows.values():
            if row["id"] == row_id:
                row["stored_at"] = stored_at
                return
        raise AssertionError(f"mark_stored called for unknown row id {row_id}")

    def row(self, device_id: str, seq: int) -> dict[str, Any]:
        return self.rows[(device_id, seq)]


class FakeQueries:
    """ReadingQueries double that records the limit it was asked for."""

    def __init__(
        self,
        latest_rows: list[dict] | None = None,
        stats_result: dict | None = None,
        is_healthy: bool = True,
    ):
        self.latest_rows = [] if latest_rows is None else latest_rows
        self.stats_result = (
            {"total": 0, "abnormal": 0, "devices": 0, "latest_received_at": None}
            if stats_result is None
            else stats_result
        )
        self.is_healthy = is_healthy
        self.latest_calls: list[int] = []

    def latest(self, limit: int) -> list[dict]:
        self.latest_calls.append(limit)
        return self.latest_rows

    def stats(self) -> dict:
        return self.stats_result

    def healthy(self) -> bool:
        return self.is_healthy


class FakeProcess:
    """Stand-in for the injected process(reading) callable."""

    def __init__(self, outcome: str = "stored", error: Exception | None = None):
        self.outcome = outcome
        self.error = error
        self.received: list[Reading] = []

    def __call__(self, reading: Reading) -> str:
        self.received.append(reading)
        if self.error is not None:
            raise self.error
        return self.outcome


@pytest.fixture
def make_clock():
    """Factory: make_clock([t1, t2], events=None) -> FakeClock."""
    return FakeClock


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def queries() -> FakeQueries:
    return FakeQueries()


@pytest.fixture
def default_limits() -> Limits:
    return DEFAULT_LIMITS
