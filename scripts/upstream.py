#!/usr/bin/env python3
"""Synthetic HTTP outcomes with an authoritative count of requests received."""

import argparse
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time


class Fixture(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=0):
        super().__init__(("127.0.0.1", port), Handler)
        self.lock = threading.Lock()
        self.attempts = defaultdict(list)

    def records(self, request_id):
        with self.lock:
            return list(self.attempts[request_id])


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            # Envoy may reset a pooled HTTP/1 connection when retrying a response.
            pass

    def do_GET(self):
        request_id = self.headers.get("x-demo-id", "manual")
        with self.server.lock:
            records = self.server.attempts[request_id]
            attempt = len(records) + 1
            sequence = {
                "/recover": [503, 200],
                "/sequence": [503, 500, 200],
                "/repeat": [503, 503, 200],
                "/always": [503],
            }.get(self.path, [404])
            status = sequence[min(attempt - 1, len(sequence) - 1)]
            record = {
                "id": request_id, "attempt": attempt, "status": status,
                "at": time.monotonic(),
                "policy_header": self.headers.get("x-demo-policy"),
            }
            records.append(record)
        body = json.dumps({"id": request_id, "attempt": attempt, "status": status}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18000)
    args = parser.parse_args()
    with Fixture(args.port) as server:
        print(f"Synthetic upstream on 127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
