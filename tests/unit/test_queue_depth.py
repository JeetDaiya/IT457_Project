"""Queue-depth sampler and purge (Stage C): a fake SQS client, no AWS."""

from __future__ import annotations

import io

import pytest

from loadtest import queue_depth as qd

URL = "https://sqs.ap-south-1.amazonaws.com/123456789012/mini-hs-readings"


class FakeSqs:
    def __init__(self, depths=((0, 0),), fail_at=(), purge_error=None):
        self.depths = list(depths)
        self.fail_at = set(fail_at)
        self.purge_error = purge_error
        self.reads = 0
        self.purged = []

    def get_queue_attributes(self, QueueUrl, AttributeNames):
        assert QueueUrl == URL
        assert set(AttributeNames) == set(qd.ATTRIBUTES)
        index = self.reads
        self.reads += 1
        if index in self.fail_at:
            raise RuntimeError("throttled")
        visible, not_visible = self.depths[min(index, len(self.depths) - 1)]
        return {
            "Attributes": {
                "ApproximateNumberOfMessages": str(visible),
                "ApproximateNumberOfMessagesNotVisible": str(not_visible),
            }
        }

    def purge_queue(self, QueueUrl):
        if self.purge_error:
            raise self.purge_error
        self.purged.append(QueueUrl)


class Clock:
    """Fake time: sleep() moves it, so the schedule can be checked without waiting."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def run_sample(client, **kw):
    clock, out = Clock(), io.StringIO()
    rows = qd.sample(client, URL, out, clock=clock.monotonic, sleep=clock.sleep, **kw)
    return rows, out.getvalue().splitlines(), clock


def test_depth_reads_both_counts_as_integers():
    assert qd.depth(FakeSqs([(7, 3)]), URL) == (7, 3)


def test_sample_writes_header_and_one_row_per_interval():
    client = FakeSqs([(100, 0), (60, 10), (0, 5), (0, 0)])
    rows, lines, _ = run_sample(client, interval=5, max_seconds=15)
    assert rows == 4  # at 0, 5, 10 and 15 s
    assert lines[0] == "time_utc,visible,not_visible"
    assert [line.split(",")[1:] for line in lines[1:]] == [
        ["100", "0"], ["60", "10"], ["0", "5"], ["0", "0"],
    ]  # fmt: skip
    assert all(line.split(",")[0].endswith("Z") for line in lines[1:])


def test_sample_keeps_a_fixed_schedule_even_with_slow_reads():
    clock = Clock()

    class Slow(FakeSqs):
        def get_queue_attributes(self, **kw):
            clock.now += 1.5  # each read takes 1.5 s
            return super().get_queue_attributes(**kw)

    out = io.StringIO()
    qd.sample(
        Slow(), URL, out, interval=5, max_seconds=10,
        clock=clock.monotonic, sleep=clock.sleep,
    )  # fmt: skip
    assert clock.sleeps == [3.5, 3.5]  # next sample is due at 5 and 10, not 6.5 and 13


def test_sample_skips_a_failed_read_and_goes_on(capsys):
    rows, lines, _ = run_sample(FakeSqs(fail_at={1}), interval=5, max_seconds=10)
    assert rows == 2
    assert len(lines) == 3
    assert "sample skipped" in capsys.readouterr().err


def test_purge_waits_a_minute_then_reports_the_depth():
    waited = []
    assert qd.purge(FakeSqs([(0, 0)]), URL, sleep=waited.append) == (0, 0)
    assert waited == [60]


def test_purge_reports_leftovers():
    assert qd.purge(FakeSqs([(5, 1)]), URL, sleep=lambda s: None) == (5, 1)


def test_parse_args_needs_a_queue_url(monkeypatch):
    monkeypatch.delenv("SQS_QUEUE_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        qd.parse_args(["depth"])
    assert exc.value.code == 2
    monkeypatch.setenv("SQS_QUEUE_URL", URL)
    assert qd.parse_args(["sample"]).queue_url == URL
    assert qd.parse_args(["sample", "--interval", "2"]).interval == 2


@pytest.mark.parametrize("bad", [["nope"], ["sample", "--interval", "0"]])
def test_parse_args_rejects_bad_input(monkeypatch, bad):
    monkeypatch.setenv("SQS_QUEUE_URL", URL)
    with pytest.raises(SystemExit) as exc:
        qd.parse_args(bad)
    assert exc.value.code == 2
