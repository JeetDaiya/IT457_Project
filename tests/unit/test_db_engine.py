"""build_engine: a dead database connection must fail in about a minute, not hang.

Seen on Stage C: the worker froze inside the pool's health check on a connection RDS had
dropped, because nothing bounded the wait. The timeouts are libpq options passed through
psycopg2, so the test also checks that libpq accepts every keyword.
"""

from __future__ import annotations

import psycopg2.extensions

from app import db


def captured_engine_kwargs(monkeypatch) -> dict:
    seen: dict = {}

    def fake_create_engine(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return "engine"

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    assert db.build_engine("postgresql+psycopg2://u:p@h/d") == "engine"
    return seen


def test_connection_timeouts_are_set(monkeypatch):
    args = captured_engine_kwargs(monkeypatch)["connect_args"]
    assert 0 < args["connect_timeout"] <= 30
    assert args["keepalives"] == 1
    assert 0 < args["keepalives_idle"] <= 60
    assert 0 < args["keepalives_interval"] <= 30
    assert 0 < args["keepalives_count"] <= 5
    # Bounds how long an in-flight query waits for an unanswered packet (milliseconds).
    assert 0 < args["tcp_user_timeout"] <= 60_000


def test_libpq_accepts_every_connect_arg(monkeypatch):
    args = captured_engine_kwargs(monkeypatch)["connect_args"]
    psycopg2.extensions.make_dsn(
        "host=localhost dbname=x", **args
    )  # raises on a bad keyword


def test_pool_settings_are_unchanged(monkeypatch):
    kwargs = captured_engine_kwargs(monkeypatch)
    assert (kwargs["pool_size"], kwargs["max_overflow"]) == (20, 20)
    assert kwargs["pool_pre_ping"] is True
