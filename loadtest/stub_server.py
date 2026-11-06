"""Calibration stub: answers 201 after a fixed delay and stores nothing.

Used only to test the generator on its own. The delay mimics the Mumbai to us-east-1
round trip so the generator holds as many requests in flight as in a real run.
"""

import argparse

import gevent
from gevent.pywsgi import WSGIServer

BODY = b'{"outcome":"stored"}'


def make_app(delay: float):
    def app(environ, start_response):
        environ["wsgi.input"].read(int(environ.get("CONTENT_LENGTH") or 0))
        gevent.sleep(delay)
        start_response(
            "201 Created",
            [("Content-Type", "application/json"), ("Content-Length", str(len(BODY)))],
        )
        return [BODY]

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--delay", type=float, default=0.22, help="seconds")
    args = parser.parse_args()
    WSGIServer((args.host, args.port), make_app(args.delay), log=None).serve_forever()
