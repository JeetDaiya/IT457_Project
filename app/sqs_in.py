"""Interface layer (SQS, Stage C): read readings from the queue and hand each to the processor.

The IoT Core rule drops every MQTT message into SQS; the body is the same reading JSON.
A message is deleted only after it was handled for good: stored, duplicate, or rejected
as invalid (retrying cannot help). Any other error leaves it in the queue, and SQS shows
it again after the visibility timeout, so a database outage loses nothing.
"""

import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from app.rules import Reading
from app.service import ProcessReading, UnknownPatient

if TYPE_CHECKING:
    from app.settings import Settings

log = logging.getLogger(__name__)

MAX_MESSAGES = 10  # the most SQS returns per receive
WAIT_SECONDS = 20  # long poll: returns at once when a message arrives
ERROR_PAUSE_S = 2  # breathing room after a failure, so an outage is not a busy loop


def handle_body(body: str, process: ProcessReading) -> bool:
    """Process one message body. Return True when the message may be deleted from the
    queue, False when it must stay so SQS delivers it again. Never raises."""
    try:
        outcome = process(Reading.model_validate_json(body))
    except ValidationError as exc:
        log.warning("rejected invalid reading: %s", exc)
    except UnknownPatient as exc:
        log.warning("rejected reading for unknown patient_ref: %s", exc)
    except Exception:
        log.exception("failed to process reading; it stays in the queue")
        return False
    else:
        log.debug("reading %s", outcome)
    return True


def poll_once(client: Any, queue_url: str, process: ProcessReading) -> bool:
    """Receive up to 10 messages, process them, delete the finished ones in one call.
    Return True when any message failed unexpectedly. AWS errors propagate to the caller."""
    response = client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=MAX_MESSAGES,
        WaitTimeSeconds=WAIT_SECONDS,
    )
    entries = []
    any_failed = False
    for index, message in enumerate(response.get("Messages", [])):
        if handle_body(message["Body"], process):
            entries.append(
                {"Id": str(index), "ReceiptHandle": message["ReceiptHandle"]}
            )
        else:
            any_failed = True
    if entries:
        result = client.delete_message_batch(QueueUrl=queue_url, Entries=entries)
        for failure in result.get("Failed", []):
            # The reading is stored; the message comes back and is ignored as a duplicate.
            log.warning("could not delete message from the queue: %s", failure)
    return any_failed


def run(settings: "Settings", process: ProcessReading, client: Any = None) -> None:
    """Poll settings.sqs_queue_url forever. One bad message or one failed AWS call never
    stops the loop."""
    if client is None:
        import boto3  # only the SQS mode needs it; the region comes from AWS_DEFAULT_REGION

        client = boto3.client("sqs")
    log.info("polling SQS queue %s", settings.sqs_queue_url)
    while True:
        try:
            failed = poll_once(client, settings.sqs_queue_url, process)
        except Exception:
            log.exception("SQS request failed; retrying")
            failed = True
        if failed:
            time.sleep(ERROR_PAUSE_S)
