"""Application layer: the one use case shared by HTTP and MQTT, and the ports it needs.

The ports (`ReadingStore`, `Clock`, `ReadingQueries`) are defined here and implemented
elsewhere (db.py), so this module never imports infrastructure.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Reading(BaseModel):
    """One vital-signs reading. Out-of-range values are rejected (HTTP 422)."""

    model_config = ConfigDict(frozen=True)

    device_id: str = Field(min_length=1)
    patient_ref: str = Field(min_length=1)  # a code such as "P0007", never a name
    heart_rate: int = Field(ge=20, le=250)
    spo2: int = Field(ge=50, le=100)
    temperature: float = Field(ge=30, le=45)
    seq: int = Field(ge=1)
    sent_at: AwareDatetime


@dataclass(frozen=True)
class Limits:
    """Normal ranges. A valid value outside them marks the reading abnormal."""

    heart_rate_min: int
    heart_rate_max: int
    spo2_min: int
    temperature_min: float
    temperature_max: float


def is_abnormal(reading: Reading, limits: Limits) -> bool:
    return (
        not limits.heart_rate_min <= reading.heart_rate <= limits.heart_rate_max
        or reading.spo2 < limits.spo2_min
        or not limits.temperature_min <= reading.temperature <= limits.temperature_max
    )


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
