"""Calibration stub: a tiny MQTT 3.1.1 broker that stores nothing.

It accepts connections and answers every QoS 1 PUBLISH with a PUBACK after a fixed delay.
Used only to test the MQTT generator on its own. The delay mimics the Mumbai to us-east-1
round trip so the generator holds as many messages in flight as in a real run.
Stdlib only, so it also runs on a bare machine: python loadtest/stub_mqtt_broker.py
"""

import argparse
import asyncio
import threading
from typing import Self

CONNACK = b"\x20\x02\x00\x00"
PINGRESP = b"\xd0\x00"
CONNECT, PUBLISH, PINGREQ, DISCONNECT = 1, 3, 12, 14


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
    """Return (packet type, flags, body) of the next packet."""
    first = (await reader.readexactly(1))[0]
    length, shift = 0, 0
    while True:
        byte = (await reader.readexactly(1))[0]
        length |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            break
    body = await reader.readexactly(length) if length else b""
    return first >> 4, first & 0x0F, body


class StubBroker:
    """The stub, run in a background thread (used by main() and by the tests)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0, delay: float = 0.22):
        self.host = host
        self.port = port
        self.delay = delay
        self.publish_count = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._writers: set[asyncio.StreamWriter] = set()

    def start(self) -> Self:
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("stub broker did not start")
        return self

    def stop(self) -> None:
        if self._loop is not None and self._thread is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(5)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _serve(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        server = loop.run_until_complete(
            asyncio.start_server(self._handle, self.host, self.port)
        )
        self.port = server.sockets[0].getsockname()[1]
        self._ready.set()
        loop.run_forever()
        server.close()
        for writer in list(self._writers):
            writer.close()
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.close()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        loop = asyncio.get_running_loop()
        try:
            while True:
                kind, flags, body = await _read_packet(reader)
                if kind == CONNECT:
                    writer.write(CONNACK)
                elif kind == PUBLISH:
                    self.publish_count += 1
                    if (flags >> 1) & 3 == 1:  # QoS 1: packet id follows the topic
                        topic_len = int.from_bytes(body[:2], "big")
                        packet_id = body[2 + topic_len : 4 + topic_len]
                        loop.call_later(self.delay, self._puback, writer, packet_id)
                elif kind == PINGREQ:
                    writer.write(PINGRESP)
                elif kind == DISCONNECT:
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass  # the client went away; pending PUBACKs are simply dropped
        finally:
            self._writers.discard(writer)
            writer.close()

    @staticmethod
    def _puback(writer: asyncio.StreamWriter, packet_id: bytes) -> None:
        if not writer.is_closing():
            writer.write(b"\x40\x02" + packet_id)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1884)
    parser.add_argument("--delay", type=float, default=0.22, help="seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    broker = StubBroker(args.host, args.port, args.delay).start()
    print(
        f"stub MQTT broker on {args.host}:{broker.port}, PUBACK delay {args.delay} s",
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        broker.stop()


if __name__ == "__main__":
    main()
