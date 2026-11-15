"""SQS queue depth for Stage C runs. Runs on the EC2 inside the worker image (boto3, instance role).

    python queue_depth.py depth                    one line: "<visible> <not_visible>"
    python queue_depth.py sample [--interval 5] [--max-seconds N]
                                                   CSV time_utc,visible,not_visible, one row per interval, until killed
    python queue_depth.py purge                    PurgeQueue, wait 60 s, exit 1 unless the queue is empty (needs sqs:PurgeQueue)

Stdlib plus boto3 only and no imports from this repo, so the script can be piped to
`docker compose run --rm -T worker python - <mode>` without being copied to the VM.
The queue URL comes from --queue-url or SQS_QUEUE_URL, the region from AWS_DEFAULT_REGION.
"""

import argparse
import os
import sys
import time
from datetime import UTC, datetime

PURGE_WAIT_S = 60  # AWS: a purge can take up to 60 seconds to finish
ATTRIBUTES = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def depth(client, queue_url: str) -> tuple[int, int]:
    """(visible, not_visible): waiting in the queue, and received but not yet deleted."""
    attrs = client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=ATTRIBUTES)[
        "Attributes"
    ]
    return int(attrs[ATTRIBUTES[0]]), int(attrs[ATTRIBUTES[1]])


def sample(
    client,
    queue_url: str,
    out,
    interval: float = 5.0,
    max_seconds: float = 0,
    clock=time.monotonic,
    sleep=time.sleep,
) -> int:
    """Write a CSV row every `interval` seconds on a fixed schedule; return the number of rows.

    A failed read is skipped, not fatal: the sampler must not stop in the middle of a run.
    max_seconds=0 means until the process is stopped.
    """
    out.write("time_utc,visible,not_visible\n")
    out.flush()
    start, rows, n = clock(), 0, 0
    while max_seconds <= 0 or n * interval <= max_seconds:
        wait = start + n * interval - clock()
        if wait > 0:
            sleep(wait)
        n += 1
        try:
            visible, not_visible = depth(client, queue_url)
        except Exception as exc:  # noqa: BLE001 - keep sampling through a short AWS error
            print(f"sample skipped: {exc}", file=sys.stderr, flush=True)
            continue
        out.write(f"{stamp()},{visible},{not_visible}\n")
        out.flush()
        rows += 1
    return rows


def purge(client, queue_url: str, sleep=time.sleep) -> tuple[int, int]:
    """Empty the queue and return its depth after AWS had time to finish."""
    client.purge_queue(QueueUrl=queue_url)
    sleep(PURGE_WAIT_S)
    return depth(client, queue_url)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["depth", "sample", "purge"])
    parser.add_argument("--queue-url", default=os.environ.get("SQS_QUEUE_URL", ""))
    parser.add_argument("--interval", type=float, default=5.0, help="seconds")
    parser.add_argument("--max-seconds", type=float, default=0, help="0 = until killed")
    opts = parser.parse_args(argv)
    if not opts.queue_url:
        parser.error("set --queue-url or SQS_QUEUE_URL")
    if opts.interval <= 0:
        parser.error("--interval must be positive")
    return opts


def main(argv: list[str]) -> int:
    opts = parse_args(argv)
    import boto3  # imported here so the functions above run (and test) without boto3

    client = boto3.client("sqs")
    if opts.mode == "depth":
        print(*depth(client, opts.queue_url))
        return 0
    if opts.mode == "sample":
        try:
            sample(client, opts.queue_url, sys.stdout, opts.interval, opts.max_seconds)
        except KeyboardInterrupt:
            pass
        return 0
    try:
        visible, not_visible = purge(client, opts.queue_url)
    except Exception as exc:  # say what is missing instead of a traceback
        if "AccessDenied" in str(exc):
            print(
                "purge refused: the instance role lacks sqs:PurgeQueue on this queue"
                " (ask the lead, or empty the queue by hand in the console)",
                file=sys.stderr,
            )
            return 1
        raise
    print(visible, not_visible)
    return 0 if visible == 0 and not_visible == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
