"""Composition root: the only module that knows every piece and wires them together.

Run with `python -m app.main api` or `python -m app.main worker` (same image, two containers).
"""

import logging
import os
import sys
from collections.abc import Callable
from functools import partial

import uvicorn

from app.api import create_app
from app.db import PostgresReadingStore, SystemClock, build_engine, init_schema
from app.service import Clock, ProcessReading, ReadingStore, process_reading
from app.settings import Settings, load_settings

API_PORT = 8000


def build_processor(
    settings: Settings, store: ReadingStore, clock: Clock
) -> ProcessReading:
    return partial(process_reading, store=store, clock=clock, limits=settings.limits())


def _wire(settings: Settings) -> tuple[PostgresReadingStore, ProcessReading]:
    logging.basicConfig(level=settings.log_level)
    engine = build_engine(settings.database_url)
    init_schema(engine, settings.seed_patients)
    store = PostgresReadingStore(engine)
    return store, build_processor(settings, store, SystemClock())


def _run_api(settings: Settings) -> None:
    store, process = _wire(settings)
    uvicorn.run(create_app(process, store), host="0.0.0.0", port=API_PORT)


def _run_worker(settings: Settings) -> None:
    from app import mqtt_in

    _, process = _wire(settings)
    mqtt_in.run(settings, process)


_MODES: dict[str, Callable[[Settings], None]] = {"api": _run_api, "worker": _run_worker}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in _MODES:
        print(f"usage: python -m app.main [{'|'.join(_MODES)}]", file=sys.stderr)
        return 2
    _MODES[argv[0]](load_settings(os.environ))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
