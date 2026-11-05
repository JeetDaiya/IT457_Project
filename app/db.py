"""Infrastructure: PostgreSQL storage (SQLAlchemy Core + psycopg2) and the system clock."""

from datetime import UTC, datetime

import psycopg2.errors
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.rules import Reading
from app.service import UnknownPatient

_SCHEMA_LOCK_KEY = 457_001  # arbitrary; makes concurrent init_schema calls take turns

_CREATE_PATIENTS = """
CREATE TABLE IF NOT EXISTS patients (
    patient_ref TEXT PRIMARY KEY,
    name        TEXT NOT NULL
)"""

_CREATE_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id          BIGSERIAL PRIMARY KEY,
    device_id   TEXT             NOT NULL,
    patient_ref TEXT             NOT NULL REFERENCES patients (patient_ref),
    heart_rate  INTEGER          NOT NULL,
    spo2        INTEGER          NOT NULL,
    temperature DOUBLE PRECISION NOT NULL,
    seq         BIGINT           NOT NULL,
    sent_at     TIMESTAMPTZ      NOT NULL,
    abnormal    BOOLEAN          NOT NULL,
    received_at TIMESTAMPTZ      NOT NULL,
    stored_at   TIMESTAMPTZ,
    UNIQUE (device_id, seq)
)"""

_INSERT_READING = text("""
INSERT INTO readings
    (device_id, patient_ref, heart_rate, spo2, temperature, seq, sent_at, abnormal, received_at)
VALUES
    (:device_id, :patient_ref, :heart_rate, :spo2, :temperature, :seq, :sent_at, :abnormal,
     :received_at)
ON CONFLICT (device_id, seq) DO NOTHING
RETURNING id""")


def build_engine(database_url: str) -> Engine:
    # Pool sized to match FastAPI's default worker-thread count (40), so threads rarely wait.
    return create_engine(
        database_url, pool_size=20, max_overflow=20, pool_pre_ping=True
    )


def init_schema(engine: Engine, seed_patients: int) -> None:
    """Create the tables and seed synthetic patients P0001..P{n}. Safe to repeat and to
    run from several processes at once (api and worker both call it at startup)."""
    patients = [
        {"ref": f"P{i:04d}", "name": f"Synthetic Patient {i:04d}"}
        for i in range(1, seed_patients + 1)
    ]
    with engine.begin() as conn:
        conn.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SCHEMA_LOCK_KEY}
        )
        conn.execute(text(_CREATE_PATIENTS))
        conn.execute(text(_CREATE_READINGS))
        if patients:
            conn.execute(
                text(
                    "INSERT INTO patients (patient_ref, name) VALUES (:ref, :name) "
                    "ON CONFLICT DO NOTHING"
                ),
                patients,
            )


class PostgresReadingStore:
    """Implements both the write port (ReadingStore) and the read port (ReadingQueries)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(
        self, reading: Reading, abnormal: bool, received_at: datetime
    ) -> int | None:
        params = {
            **reading.model_dump(),
            "abnormal": abnormal,
            "received_at": received_at,
        }
        try:
            with self._engine.begin() as conn:
                return conn.execute(_INSERT_READING, params).scalar_one_or_none()
        except IntegrityError as exc:
            if isinstance(exc.orig, psycopg2.errors.ForeignKeyViolation):
                raise UnknownPatient(reading.patient_ref) from exc
            raise

    def mark_stored(self, row_id: int, stored_at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE readings SET stored_at = :stored_at WHERE id = :id"),
                {"stored_at": stored_at, "id": row_id},
            )

    def latest(self, limit: int) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM readings ORDER BY id DESC LIMIT :limit"),
                {"limit": limit},
            )
            return [dict(row._mapping) for row in rows]

    def stats(self) -> dict:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT count(*) AS total, "
                    "count(*) FILTER (WHERE abnormal) AS abnormal, "
                    "count(DISTINCT device_id) AS devices, "
                    "max(received_at) AS latest_received_at FROM readings"
                )
            ).one()
            return dict(row._mapping)

    def healthy(self) -> bool:
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
