"""Application layer: the one use case shared by HTTP and MQTT, and the ports it needs.

The ports (`ReadingStore`, `Clock`, `ReadingQueries`) are defined here and implemented
elsewhere (db.py), so this module never imports infrastructure.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol

from app.rules import Limits, Reading, is_abnormal

Outcome = Literal["stored", "duplicate"]
ProcessReading = Callable[[Reading], Outcome]


class UnknownPatient(Exception):
    """The reading's patient_ref is not in the patients table."""


class ReadingStore(Protocol):
    def add(
        self, reading: Reading, abnormal: bool, received_at: datetime
    ) -> int | None:
        """Insert the reading and commit. Return the new row id, or None if
        (device_id, seq) already exists. Raise UnknownPatient for an unseeded patient."""
        ...

    def mark_stored(self, row_id: int, stored_at: datetime) -> None:
        """Record when the insert became durable."""
        ...


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...


class ReadingQueries(Protocol):
    """Read side used by the HTTP endpoints."""

    def latest(self, limit: int) -> list[dict]: ...

    def stats(self) -> dict: ...

    def healthy(self) -> bool: ...


def process_reading(
    reading: Reading, *, store: ReadingStore, clock: Clock, limits: Limits
) -> Outcome:
    received_at = clock.now()
    row_id = store.add(reading, is_abnormal(reading, limits), received_at)
    if row_id is None:
        return "duplicate"
    store.mark_stored(row_id, clock.now())
    return "stored"
