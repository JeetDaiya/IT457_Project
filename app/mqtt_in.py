"""Interface layer (MQTT): subscribe to the broker and hand each message to the processor.

No business logic lives here: parse, call `process`, and never let one bad message stop the loop.
"""

import logging
from typing import TYPE_CHECKING

import paho.mqtt.client as mqtt
from pydantic import ValidationError

from app.service import ProcessReading, Reading, UnknownPatient

if TYPE_CHECKING:
    from app.main import Settings

log = logging.getLogger(__name__)

# Fixed ID + clean_session=False: the broker keeps QoS 1 messages while the worker is down.
# Only valid with one worker per CLIENT_ID (a second one with the same ID kicks the first off).
CLIENT_ID = "healthsuite-worker"
QOS = 1


def handle_message(payload: bytes, process: ProcessReading) -> None:
    """Parse one message and process it. Never raises, so the loop survives and the
    broker is still acknowledged. A duplicate is a normal outcome, not an error."""
    try:
        outcome = process(Reading.model_validate_json(payload))
    except ValidationError as exc:
        log.warning("rejected invalid reading: %s", exc)
    except UnknownPatient as exc:
        log.warning("rejected reading for unknown patient_ref: %s", exc)
    except Exception:
        log.exception("failed to process reading")
    else:
        log.debug("reading %s", outcome)


def run(settings: "Settings", process: ProcessReading) -> None:
    """Connect, subscribe to settings.mqtt_topic at QoS 1 and process messages forever."""
    client = mqtt.Client(client_id=CLIENT_ID, clean_session=False)

    def on_connect(client, userdata, flags, rc):
        if rc != 0:
            log.error("MQTT connection refused, rc=%s", rc)
            return
        log.info("connected to MQTT broker; subscribing to %s", settings.mqtt_topic)
        client.subscribe(settings.mqtt_topic, qos=QOS)  # again after every reconnect

    def on_message(client, userdata, message):
        # paho sends the PUBACK only after this returns, i.e. after the database write.
        handle_message(message.payload, process)

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(settings.mqtt_host, settings.mqtt_port)
    client.loop_forever(retry_first_connection=True)
