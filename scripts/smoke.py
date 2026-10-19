#!/usr/bin/env python3
"""Exercise the real Envoy router and a native request-scoped policy module."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import threading
import time

from upstream import Fixture

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def request(port, path, policy="default", request_id="", method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers={"x-demo-policy": policy, "x-demo-id": request_id})
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


def wait_for(predicate, process, description, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        check(process.poll() is None, f"Envoy exited; inspect {BUILD / 'envoy.log'}")
        try:
            if predicate():
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.02)
    raise AssertionError(f"timed out: {description}")


def events():
    result = []
    for line in (BUILD / "envoy.log").read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "event" in value:
            result.append(value)
    return result


def decisions(request_id):
    return [e for e in events() if e.get("id") == request_id and e["event"] == "decision"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    BUILD.mkdir(exist_ok=True)
    # Never leave an earlier successful result looking like this run's evidence.
    (BUILD / "results.json").unlink(missing_ok=True)
    binary = Path(os.environ.get("ENVOY_BINARY", BUILD / "envoy-static")).resolve()
    check(binary.is_file(), "build Envoy first, or set ENVOY_BINARY to the matching patched binary")
    check((BUILD / "libattempt_policy.so").is_file(), "run scripts/build.sh first")
    version_output = subprocess.check_output([str(binary), "--version"], text=True)
    version = version_output.split("version:", 1)[-1].strip()
    revision = (ROOT / "envoy-revision.txt").read_text().strip()
    check(revision in version, "Envoy binary revision differs from envoy-revision.txt")
    summary = []
    with Fixture() as upstream:
        thread = threading.Thread(target=upstream.serve_forever)
        thread.start()
        process = None
        reservations = []
        try:
            for _ in range(2):
                sock = socket.socket()
                sock.bind(("127.0.0.1", 0))
                reservations.append(sock)
            admin, proxy = [sock.getsockname()[1] for sock in reservations]
            config = (ROOT / "envoy.yaml").read_text()
            for original, port in [(9901, admin), (10000, proxy), (18000, upstream.server_port)]:
                config = config.replace(f"port_value: {original}", f"port_value: {port}")
            (BUILD / "smoke.yaml").write_text(config)
            env = dict(os.environ, ENVOY_DYNAMIC_MODULES_SEARCH_PATH=str(BUILD))
            for sock in reservations:
                sock.close()
            with (BUILD / "envoy.log").open("w") as log:
                process = subprocess.Popen(
                    [str(binary), "-c", str(BUILD / "smoke.yaml"), "--concurrency", "2",
                     "--disable-hot-restart", "--log-level", "warning"],
                    env=env, stdout=log, stderr=subprocess.STDOUT,
                )
                wait_for(lambda: request(admin, "/ready")[0] == 200, process, "Envoy readiness", 30)

                def run_case(name, policy, path, expected_status, expected_attempts):
                    status, body, headers = request(proxy, path, policy, name)
                    records = upstream.records(name)
                    check(status == expected_status, f"{name}: status {status}, body {body!r}")
                    check(len(records) == expected_attempts, f"{name}: received {len(records)} attempts")
                    check(all(r["policy_header"] is None for r in records), "policy selector leaked upstream")
                    summary.append({"case": name, "status": status, "attempts": len(records)})
                    print(f"PASS {name}: HTTP {status}, {len(records)} upstream attempts", flush=True)
                    return records

                run_case("default-route", "default", "/recover", 200, 2)
                check(not decisions("default-route"), "unregistered request invoked policy")
                run_case("deny", "deny", "/recover", 503, 1)
                records = run_case("allow", "retry", "/recover", 200, 2)
                check(records[1]["at"] - records[0]["at"] >= 0.12, "custom delay was not honored")
                run_case("outcome-aware", "selective", "/sequence", 500, 2)
                check([e["allow"] for e in decisions("outcome-aware")] == [True, False],
                      "expected allow on 503 followed by deny on 500")
                run_case("default-sequence", "default", "/sequence", 200, 3)
                run_case("history-different", "history", "/sequence", 200, 3)
                run_case("history-repeated", "history", "/repeat", 503, 2)
                check([e["allow"] for e in decisions("history-repeated")] == [True, False],
                      "history policy did not stop on a repeated failure")
                run_case("default-repeated", "default", "/repeat", 200, 3)
                run_case("retry-limit", "retry", "/always", 503, 3)
                check(all(e["allow"] for e in decisions("retry-limit")), "policy denied before limit")
                check(len(decisions("retry-limit")) == 3, "missing decision at exhausted retry limit")

                check(request(admin, "/runtime_modify?upstream.use_retry=0", method="POST")[0] == 200,
                      "cannot disable Envoy retries")
                run_case("runtime-veto", "retry", "/recover", 503, 1)
                check(decisions("runtime-veto")[0]["allow"], "did not observe Envoy veto of allow")
                run_case("runtime-default", "default", "/recover", 503, 1)
                check(request(admin, "/runtime_modify?upstream.use_retry=100", method="POST")[0] == 200,
                      "cannot restore Envoy retries")
                run_case("runtime-restored", "retry", "/recover", 200, 2)

                breaker_key = "circuit_breakers.synthetic.default.max_retries"
                check(request(admin, f"/runtime_modify?{breaker_key}=0", method="POST")[0] == 200,
                      "cannot set retry circuit breaker")
                run_case("circuit-breaker-veto", "retry", "/recover", 503, 1)
                check(decisions("circuit-breaker-veto")[0]["allow"], "policy denied before circuit breaker")
                check(request(admin, f"/runtime_modify?{breaker_key}=64", method="POST")[0] == 200,
                      "cannot restore retry capacity")

                run_case("deadline", "slow", "/recover", 504, 1)
                time.sleep(0.7)
                check(len(upstream.records("deadline")) == 1, "retry escaped expired deadline")

                with socket.create_connection(("127.0.0.1", proxy), timeout=5) as client:
                    client.sendall(b"GET /recover HTTP/1.1\r\nHost: local\r\nx-demo-id: cancelled\r\n"
                                   b"x-demo-policy: slow\r\n\r\n")
                    wait_for(lambda: bool(decisions("cancelled")), process, "policy decision before cancellation")
                # Observe cancellation before the route deadline could mask a failure.
                wait_for(lambda: any(e["event"] == "destroyed" and e.get("id") == "cancelled"
                                     for e in events()), process, "cancelled request destruction", 0.7)
                time.sleep(1.6)
                check(len(upstream.records("cancelled")) == 1, "retry escaped downstream cancellation")
                summary.append({"case": "cancelled", "attempts": 1})
                print("PASS cancellation during backoff: one upstream attempt", flush=True)

                run_case("invalid-policy", "invalid", "/recover", 400, 0)

                def concurrent_case(index):
                    name = f"concurrent-{index}"
                    # Identical policies must retain separate observed histories.
                    path = "/sequence" if index % 2 else "/repeat"
                    status, _, _ = request(proxy, path, "history", name)
                    expected = (200, 3) if index % 2 else (503, 2)
                    actual = (status, len(upstream.records(name)))
                    check(actual == expected, f"request isolation: {name}, expected {expected}, got {actual}")

                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(concurrent_case, range(32)))
                summary.append({"case": "concurrent-isolation", "requests": 32})
                print("PASS 32 concurrent requests across two Envoy workers", flush=True)

                def all_destroyed():
                    observed = events()
                    registered = {e["id"] for e in observed if e["event"] == "registered"}
                    destroyed = {e["id"] for e in observed if e["event"] == "destroyed"}
                    return registered and registered == destroyed

                wait_for(all_destroyed, process, "all registered request tokens released")
                check(process.poll() is None, "Envoy terminated during smoke test")
                result = {
                    "tested_at": datetime.now(timezone.utc).isoformat(),
                    "platform": platform.platform(),
                    "revision": revision,
                    "envoy_version": version,
                    "envoy_sha256": digest(binary),
                    "module_sha256": digest(BUILD / "libattempt_policy.so"),
                    "patch_sha256": digest(ROOT / "patches/attempt-policy-poc.patch"),
                    "cases": summary,
                }
                (BUILD / "results.json").write_text(json.dumps(result, indent=2) + "\n")
                print(f"Evidence: {BUILD / 'results.json'}", flush=True)
        finally:
            for sock in reservations:
                sock.close()
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            upstream.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
