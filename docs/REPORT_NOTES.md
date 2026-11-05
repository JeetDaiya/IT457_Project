# Report notes

_Points to carry into the LaTeX report. The report itself is edited elsewhere, not from this repo._

- **Why IoT Core (MQTT worker effort).** Our Stage A/B worker is deliberately single-threaded. Building a
  resilient multi-threaded MQTT consumer ourselves (thread pool, DB connections, ordering, backpressure,
  reconnect and redelivery handling) would be expensive and, above all, time-consuming. AWS IoT Core removes
  that burden and handles millions of messages without these problems.
- **Persistent MQTT session in Stages A/B.** The worker uses a fixed client ID with `clean_session=False`, so
  Mosquitto queues QoS 1 messages while the worker is down. We chose the better design on purpose, so the
  restart test may show near-zero lost readings in Stages A/B too. Report that honestly; the SQS queue's
  value in Stage C is then durability that does not depend on one broker and one worker.
