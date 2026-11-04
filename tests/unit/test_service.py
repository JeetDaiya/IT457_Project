"""process_reading() orchestration, tested with in-memory fakes."""

from __future__ import annotations

import pytest
from conftest import (
    DEFAULT_LIMITS,
    T1,
    T2,
    T3,
    T4,
    FakeClock,
    InMemoryStore,
    make_reading,
)

from app.service import Limits, UnknownPatient, process_reading


def run(reading, store, clock, limits=DEFAULT_LIMITS):
    return process_reading(reading, store=store, clock=clock, limits=limits)


# ---- stored path -----------------------------------------------------------


def test_new_reading_returns_stored():
    assert run(make_reading(), InMemoryStore(), FakeClock([T1, T2])) == "stored"


def test_add_is_called_exactly_once_with_the_reading():
    store = InMemoryStore()
    reading = make_reading()
    run(reading, store, FakeClock([T1, T2]))
    assert len(store.add_calls) == 1
    assert store.add_calls[0]["reading"] == reading


def test_received_at_is_the_first_clock_value():
    store = InMemoryStore()
    run(make_reading(), store, FakeClock([T1, T2]))
    assert store.add_calls[0]["received_at"] == T1


def test_mark_stored_is_called_once_with_the_second_clock_value():
    store = InMemoryStore()
    run(make_reading(), store, FakeClock([T1, T2]))
    assert len(store.mark_calls) == 1
    assert store.mark_calls[0][1] == T2


def test_mark_stored_targets_the_row_id_returned_by_add():
    store = InMemoryStore()
    reading = make_reading()
    run(reading, store, FakeClock([T1, T2]))
    row_id = store.row(reading.device_id, reading.seq)["id"]
    assert store.mark_calls[0][0] == row_id


def test_received_at_is_not_after_stored_at():
    store = InMemoryStore()
    reading = make_reading()
    run(reading, store, FakeClock([T1, T2]))
    row = store.row(reading.device_id, reading.seq)
    assert row["received_at"] <= row["stored_at"]


def test_clock_is_read_twice_on_the_stored_path():
    clock = FakeClock([T1, T2])
    run(make_reading(), InMemoryStore(), clock)
    assert clock.calls == 2


def test_steps_happen_in_order_clock_add_clock_mark_stored():
    events: list[str] = []
    store = InMemoryStore(events=events)
    clock = FakeClock([T1, T2], events=events)
    run(make_reading(), store, clock)
    assert events == ["now", "add", "now", "mark_stored"]


# ---- abnormal flag ---------------------------------------------------------


def test_normal_reading_is_added_with_abnormal_false():
    store = InMemoryStore()
    run(make_reading(), store, FakeClock([T1, T2]))
    assert store.add_calls[0]["abnormal"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"heart_rate": 130},
        {"heart_rate": 45},
        {"spo2": 88},
        {"temperature": 39.0},
        {"temperature": 35.0},
    ],
)
def test_abnormal_reading_is_added_with_abnormal_true(overrides):
    store = InMemoryStore()
    run(make_reading(**overrides), store, FakeClock([T1, T2]))
    assert store.add_calls[0]["abnormal"] is True


def test_abnormal_reading_is_still_stored():
    store = InMemoryStore()
    assert run(make_reading(heart_rate=200), store, FakeClock([T1, T2])) == "stored"
    assert len(store.mark_calls) == 1


# ---- duplicate path --------------------------------------------------------


def test_duplicate_device_and_seq_returns_duplicate():
    store = InMemoryStore()
    first = run(make_reading(), store, FakeClock([T1, T2]))
    second = run(make_reading(), store, FakeClock([T3, T4]))
    assert (first, second) == ("stored", "duplicate")


def test_duplicate_does_not_call_mark_stored():
    store = InMemoryStore()
    run(make_reading(), store, FakeClock([T1, T2]))
    run(make_reading(), store, FakeClock([T3, T4]))
    assert len(store.mark_calls) == 1  # only the first, successful call


def test_duplicate_leaves_the_original_stored_at_untouched():
    store = InMemoryStore()
    reading = make_reading()
    run(reading, store, FakeClock([T1, T2]))
    run(reading, store, FakeClock([T3, T4]))
    assert store.row(reading.device_id, reading.seq)["stored_at"] == T2


def test_every_attempt_asks_the_store_exactly_once():
    store = InMemoryStore()
    run(make_reading(), store, FakeClock([T1, T2]))
    run(make_reading(), store, FakeClock([T3, T4]))
    assert len(store.add_calls) == 2


def test_duplicate_received_at_comes_from_the_first_clock_value():
    store = InMemoryStore()
    run(make_reading(), store, FakeClock([T1, T2]))
    run(make_reading(), store, FakeClock([T3, T4]))
    assert store.add_calls[1]["received_at"] == T3


def test_same_seq_from_a_different_device_is_not_a_duplicate():
    store = InMemoryStore(known_patients={"P0007", "P0008"})
    run(make_reading(device_id="dev-0007", seq=5), store, FakeClock([T1, T2]))
    outcome = run(
        make_reading(device_id="dev-0008", patient_ref="P0008", seq=5),
        store,
        FakeClock([T3, T4]),
    )
    assert outcome == "stored"


# ---- UnknownPatient --------------------------------------------------------


def test_unknown_patient_propagates():
    store = InMemoryStore()
    with pytest.raises(UnknownPatient):
        run(make_reading(patient_ref="P9999"), store, FakeClock([T1, T2]))


def test_unknown_patient_does_not_call_mark_stored():
    store = InMemoryStore()
    with pytest.raises(UnknownPatient):
        run(make_reading(patient_ref="P9999"), store, FakeClock([T1, T2]))
    assert store.mark_calls == []


def test_unknown_patient_exception_is_propagated_unchanged():
    raised = UnknownPatient("P9999")

    class RaisingStore(InMemoryStore):
        def add(self, reading, abnormal, received_at):
            raise raised

    with pytest.raises(UnknownPatient) as excinfo:
        run(make_reading(), RaisingStore(), FakeClock([T1, T2]))
    assert excinfo.value is raised


# ---- injected limits -------------------------------------------------------


def test_process_reading_uses_the_limits_it_is_given():
    strict = Limits(
        heart_rate_min=60,
        heart_rate_max=100,
        spo2_min=95,
        temperature_min=36.0,
        temperature_max=37.5,
    )
    reading = make_reading(
        heart_rate=55
    )  # normal by default limits, abnormal by strict

    default_store = InMemoryStore()
    run(reading, default_store, FakeClock([T1, T2]), limits=DEFAULT_LIMITS)
    strict_store = InMemoryStore()
    run(reading, strict_store, FakeClock([T1, T2]), limits=strict)

    assert default_store.add_calls[0]["abnormal"] is False
    assert strict_store.add_calls[0]["abnormal"] is True


# ---- main.build_processor --------------------------------------------------


def _settings(**env):
    from app.main import load_settings

    return load_settings({"DATABASE_URL": "postgresql://u:p@localhost/db", **env})


def test_build_processor_returns_a_callable_that_stores_a_reading():
    from app.main import build_processor

    store = InMemoryStore()
    process = build_processor(_settings(), store, FakeClock([T1, T2]))
    assert process(make_reading()) == "stored"
    assert len(store.add_calls) == 1


def test_build_processor_binds_limits_from_settings():
    from app.main import build_processor

    store = InMemoryStore()
    process = build_processor(
        _settings(HEART_RATE_MIN="60"), store, FakeClock([T1, T2])
    )
    process(make_reading(heart_rate=55))  # below the configured minimum of 60
    assert store.add_calls[0]["abnormal"] is True


def test_build_processor_with_default_settings_treats_hr_55_as_normal():
    from app.main import build_processor

    store = InMemoryStore()
    process = build_processor(_settings(), store, FakeClock([T1, T2]))
    process(make_reading(heart_rate=55))
    assert store.add_calls[0]["abnormal"] is False


def test_build_processor_reports_duplicates():
    from app.main import build_processor

    store = InMemoryStore()
    process = build_processor(_settings(), store, FakeClock([T1, T2, T3, T4]))
    assert process(make_reading()) == "stored"
    assert process(make_reading()) == "duplicate"
