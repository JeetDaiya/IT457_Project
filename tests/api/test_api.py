"""HTTP layer, tested with a fake processor and fake queries (no database)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import (
    READING_FIELDS,
    FakeProcess,
    FakeQueries,
    make_reading,
    valid_payload,
)
from fastapi.testclient import TestClient

from app.api import create_app
from app.service import UnknownPatient


@pytest.fixture
def make_client():
    def _make(process: FakeProcess | None = None, queries: FakeQueries | None = None):
        app = create_app(
            FakeProcess() if process is None else process,
            FakeQueries() if queries is None else queries,
        )
        return TestClient(app)

    return _make


# ---- POST /readings: outcome mapping --------------------------------------


def test_stored_outcome_returns_201(make_client):
    response = make_client(FakeProcess("stored")).post(
        "/readings", json=valid_payload()
    )
    assert response.status_code == 201


def test_stored_outcome_body(make_client):
    response = make_client(FakeProcess("stored")).post(
        "/readings", json=valid_payload()
    )
    assert response.json() == {"outcome": "stored"}


def test_duplicate_outcome_returns_200(make_client):
    response = make_client(FakeProcess("duplicate")).post(
        "/readings", json=valid_payload()
    )
    assert response.status_code == 200


def test_duplicate_outcome_body(make_client):
    response = make_client(FakeProcess("duplicate")).post(
        "/readings", json=valid_payload()
    )
    assert response.json() == {"outcome": "duplicate"}


def test_process_receives_a_reading_equal_to_the_payload(make_client):
    process = FakeProcess()
    make_client(process).post("/readings", json=valid_payload())
    assert process.received == [make_reading()]


def test_process_is_called_once_per_request(make_client):
    process = FakeProcess()
    client = make_client(process)
    client.post("/readings", json=valid_payload(seq=1))
    client.post("/readings", json=valid_payload(seq=2))
    assert [r.seq for r in process.received] == [1, 2]


# ---- POST /readings: validation -------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("heart_rate", 19),
        ("heart_rate", 251),
        ("spo2", 49),
        ("spo2", 101),
        ("temperature", 29.9),
        ("temperature", 45.1),
    ],
)
def test_out_of_range_value_returns_422_and_is_not_processed(make_client, field, value):
    process = FakeProcess()
    response = make_client(process).post(
        "/readings", json=valid_payload(**{field: value})
    )
    assert response.status_code == 422
    assert process.received == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("heart_rate", 20),
        ("heart_rate", 250),
        ("spo2", 50),
        ("spo2", 100),
        ("temperature", 30.0),
        ("temperature", 45.0),
    ],
)
def test_value_on_inclusive_bound_is_accepted(make_client, field, value):
    response = make_client(FakeProcess("stored")).post(
        "/readings", json=valid_payload(**{field: value})
    )
    assert response.status_code == 201


@pytest.mark.parametrize("field", READING_FIELDS)
def test_missing_field_returns_422_and_is_not_processed(make_client, field):
    payload = valid_payload()
    del payload[field]
    process = FakeProcess()
    response = make_client(process).post("/readings", json=payload)
    assert response.status_code == 422
    assert process.received == []


def test_wrong_type_returns_422(make_client):
    response = make_client().post("/readings", json=valid_payload(heart_rate="fast"))
    assert response.status_code == 422


def test_seq_of_zero_returns_422(make_client):
    response = make_client().post("/readings", json=valid_payload(seq=0))
    assert response.status_code == 422


def test_unparseable_sent_at_returns_422(make_client):
    response = make_client().post(
        "/readings", json=valid_payload(sent_at="yesterday-ish")
    )
    assert response.status_code == 422


def test_empty_json_object_returns_422(make_client):
    assert make_client().post("/readings", json={}).status_code == 422


def test_body_that_is_not_json_returns_422(make_client):
    response = make_client().post(
        "/readings",
        content="this is not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


def test_unknown_patient_returns_422(make_client):
    process = FakeProcess(error=UnknownPatient("P9999"))
    response = make_client(process).post(
        "/readings", json=valid_payload(patient_ref="P9999")
    )
    assert response.status_code == 422


# ---- GET /readings/latest --------------------------------------------------


def test_latest_defaults_to_limit_50(make_client):
    queries = FakeQueries()
    make_client(queries=queries).get("/readings/latest")
    assert queries.latest_calls == [50]


def test_latest_passes_explicit_limit_through(make_client):
    queries = FakeQueries()
    make_client(queries=queries).get("/readings/latest", params={"limit": 7})
    assert queries.latest_calls == [7]


@pytest.mark.parametrize("limit", [1, 500])
def test_latest_accepts_limit_bounds(make_client, limit):
    queries = FakeQueries()
    response = make_client(queries=queries).get(
        "/readings/latest", params={"limit": limit}
    )
    assert response.status_code == 200
    assert queries.latest_calls == [limit]


@pytest.mark.parametrize("limit", [0, 501, -1, "abc"])
def test_latest_rejects_invalid_limit_with_422(make_client, limit):
    queries = FakeQueries()
    response = make_client(queries=queries).get(
        "/readings/latest", params={"limit": limit}
    )
    assert response.status_code == 422
    assert queries.latest_calls == []


def test_latest_returns_the_rows_as_a_json_list(make_client):
    rows = [
        {
            "id": 2,
            "device_id": "dev-0007",
            "seq": 2,
            "abnormal": True,
            "stored_at": None,
        },
        {
            "id": 1,
            "device_id": "dev-0007",
            "seq": 1,
            "abnormal": False,
            "stored_at": None,
        },
    ]
    response = make_client(queries=FakeQueries(latest_rows=rows)).get(
        "/readings/latest"
    )
    assert response.status_code == 200
    assert response.json() == rows


def test_latest_returns_empty_list_when_there_are_no_rows(make_client):
    response = make_client(queries=FakeQueries(latest_rows=[])).get("/readings/latest")
    assert response.json() == []


def test_latest_serialises_datetimes_as_iso_8601(make_client):
    moment = datetime(2026, 11, 5, 9, 15, 3, 412_000, tzinfo=UTC)
    rows = [{"id": 1, "received_at": moment}]
    response = make_client(queries=FakeQueries(latest_rows=rows)).get(
        "/readings/latest"
    )
    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()[0]["received_at"]) == moment


# ---- GET /stats ------------------------------------------------------------


def test_stats_is_passed_through(make_client):
    stats = {"total": 12, "abnormal": 3, "devices": 4, "latest_received_at": None}
    response = make_client(queries=FakeQueries(stats_result=stats)).get("/stats")
    assert response.status_code == 200
    assert response.json() == stats


def test_stats_serialises_datetime_as_iso_8601(make_client):
    moment = datetime(2026, 11, 5, 9, 15, 3, 412_000, tzinfo=UTC)
    stats = {"total": 1, "abnormal": 0, "devices": 1, "latest_received_at": moment}
    response = make_client(queries=FakeQueries(stats_result=stats)).get("/stats")
    assert datetime.fromisoformat(response.json()["latest_received_at"]) == moment


# ---- GET /health -----------------------------------------------------------


def test_health_is_200_ok_when_healthy(make_client):
    response = make_client(queries=FakeQueries(is_healthy=True)).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_503_when_unhealthy(make_client):
    response = make_client(queries=FakeQueries(is_healthy=False)).get("/health")
    assert response.status_code == 503


# ---- GET / (web form) ------------------------------------------------------


def test_root_returns_html(make_client):
    response = make_client().get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_root_page_contains_a_form(make_client):
    assert "<form" in make_client().get("/").text.lower()


# ---- main(argv) ------------------------------------------------------------


def test_main_with_unknown_mode_returns_non_zero():
    from app.main import main

    assert main(["definitely-not-a-mode"]) != 0
