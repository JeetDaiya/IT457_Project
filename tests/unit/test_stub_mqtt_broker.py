"""Stub MQTT broker: CONNACK, delayed PUBACK without serialising, PINGRESP, clean close."""

from __future__ import annotations

import socket
import threading
import time

import paho.mqtt.client as mqtt
import pytest

from loadtest import stub_mqtt_broker
from loadtest.stub_mqtt_broker import StubBroker

CONNECT = b"\x10\x0e\x00\x04MQTT\x04\x02\x00\x3c\x00\x02id"


def publish_packet(
    packet_id: int | None, qos: int, topic: bytes = b"vitals/x"
) -> bytes:
    body = len(topic).to_bytes(2, "big") + topic
    if qos:
        body += packet_id.to_bytes(2, "big")
    body += b"{}"
    return bytes([0x30 | (qos << 1), len(body)]) + body


def connect(broker, timeout=2.0) -> socket.socket:
    s = socket.create_connection(("127.0.0.1", broker.port), timeout=timeout)
    s.sendall(CONNECT)
    assert recv_exact(s, 4) == b"\x20\x02\x00\x00"
    return s


def recv_exact(s, n) -> bytes:
    data = b""
    while len(data) < n:
        chunk = s.recv(n - len(data))
        if not chunk:
            break
        data += chunk
    return data


def test_connect_gets_connack():
    with StubBroker(delay=0.05) as broker:
        assert broker.port > 0
        connect(broker).close()


def test_qos1_publish_is_acked_after_the_delay():
    with StubBroker(delay=0.15) as broker:
        s = connect(broker)
        t0 = time.monotonic()
        s.sendall(publish_packet(0x1234, 1))
        assert recv_exact(s, 4) == b"\x40\x02\x12\x34"
        assert time.monotonic() - t0 >= 0.14
        s.close()
        assert broker.publish_count == 1


def test_qos0_publish_is_counted_but_not_answered():
    with StubBroker(delay=0.05) as broker:
        s = connect(broker)
        s.sendall(publish_packet(None, 0))
        s.settimeout(0.3)
        with pytest.raises(socket.timeout):
            s.recv(10)
        assert broker.publish_count == 1
        s.close()


def test_pingreq_gets_pingresp():
    with StubBroker() as broker:
        s = connect(broker)
        s.sendall(b"\xc0\x00")
        assert recv_exact(s, 2) == b"\xd0\x00"
        s.close()


def test_pending_acks_do_not_serialise():
    with StubBroker(delay=0.2) as broker:
        s = connect(broker)
        t0 = time.monotonic()
        s.sendall(b"".join(publish_packet(i, 1) for i in range(1, 31)))
        data = recv_exact(s, 4 * 30)
        elapsed = time.monotonic() - t0
        assert len(data) == 120
        ids = {int.from_bytes(data[i + 2 : i + 4], "big") for i in range(0, 120, 4)}
        assert ids == set(range(1, 31))
        assert 0.19 <= elapsed < 1.0
        s.close()


def test_disconnect_closes_the_connection():
    with StubBroker() as broker:
        s = connect(broker)
        s.sendall(b"\xe0\x00")
        assert s.recv(10) == b""
        s.close()


def test_client_leaving_with_acks_pending_does_not_hurt_the_broker():
    with StubBroker(delay=0.15) as broker:
        s = connect(broker)
        s.sendall(b"".join(publish_packet(i, 1) for i in range(1, 6)))
        s.close()
        time.sleep(0.3)
        s2 = connect(broker)
        s2.sendall(b"\xc0\x00")
        assert recv_exact(s2, 2) == b"\xd0\x00"
        s2.close()


def test_stop_closes_client_connections_and_start_returns_self():
    broker = StubBroker()
    assert broker.start() is broker
    s = connect(broker)
    broker.stop()
    s.settimeout(2)
    try:
        assert s.recv(10) == b""
    except ConnectionError:
        pass
    s.close()


def paho_client(broker, acked: dict):
    client = mqtt.Client(client_id="stubtest", clean_session=True)
    connected = threading.Event()

    def on_connect(c, u, f, rc):
        connected.set()

    def on_publish(c, u, mid):
        acked[mid] = time.monotonic()

    client.on_connect = on_connect
    client.on_publish = on_publish
    client.connect("127.0.0.1", broker.port, keepalive=60)
    client.loop_start()
    assert connected.wait(2)
    return client


def test_real_paho_client_ack_takes_at_least_the_delay():
    with StubBroker(delay=0.15) as broker:
        acked: dict = {}
        client = paho_client(broker, acked)
        t0 = time.monotonic()
        info = client.publish("vitals/x", b"{}", qos=1)
        info.wait_for_publish(timeout=2)
        assert info.is_published()
        assert acked[info.mid] - t0 >= 0.14
        client.loop_stop()
        client.disconnect()


def test_real_paho_client_50_concurrent_publishes_take_about_one_delay():
    with StubBroker(delay=0.2) as broker:
        acked: dict = {}
        client = paho_client(broker, acked)
        client.max_inflight_messages_set(100)
        t0 = time.monotonic()
        infos = [client.publish("vitals/x", b"{}", qos=1) for _ in range(60)]
        for info in infos:
            info.wait_for_publish(timeout=2)
        elapsed = time.monotonic() - t0
        assert all(i.is_published() for i in infos)
        assert 0.19 <= elapsed < 1.0
        assert broker.publish_count == 60
        client.loop_stop()
        client.disconnect()


def test_main_argument_defaults_and_overrides():
    parse = getattr(stub_mqtt_broker, "parse_args", None)
    if parse is None:
        pytest.skip("main() has no separate argument parser to test")
    o = parse([])
    assert (o.host, o.port, o.delay) == ("127.0.0.1", 1884, 0.22)
    o = parse(["--host", "0.0.0.0", "--port", "2000", "--delay", "0.5"])
    assert (o.host, o.port, o.delay) == ("0.0.0.0", 2000, 0.5)
