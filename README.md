# Envoy request-scoped retry decisions

Two requests use the same Envoy route and receive the same upstream failure.
An HTTP extension permits another attempt for one request and declines it for the
other. Envoy executes the retry and retains its retry limit, runtime controls,
route deadline and downstream cancellation behavior.

A second policy remembers the preceding response for each request: it retries
500/503 failures while their status changes, but stops on a repeated failure.
With that same policy and route, `503 → 500 → 200` succeeds in three attempts,
while `503 → 503` stops after two. This exercises request-local outcome history.

```text
request context → HTTP extension attaches request policy
                              ↓
                     Envoy sends request
                              ↓
                     upstream outcome
                              ↓
                  extension: deny or allow + delay
                              ↓
                  Envoy checks limits and schedules
```

This is an executable experiment for a proposed extension pattern. It uses a
small experimental Envoy patch; it is not a supported upstream API. It demonstrates
the mechanism and its interaction with several router controls. It does not prove
that all existing extension combinations are insufficient, or that this ABI is
suitable for upstream adoption.

## What to observe

Every request uses one route with `retry_on: 5xx`, two permitted retries and a
one-second route timeout. The cluster permits 64 concurrent retries for the
isolation test; a separate case sets its retry circuit breaker to zero. The
synthetic upstream records every request it receives.

| Request policy / fixture | Expected downstream result | Upstream attempts |
| --- | --- | --- |
| No policy; 503 then 200 | 200, ordinary route retry | 2 |
| Deny; 503 then 200 | 503 | 1 |
| Allow 503 with 150 ms delay; 503 then 200 | 200 | 2 |
| Allow only 503; 503 then 500 then 200 | 500, stop on the second outcome | 2 |
| No policy; 503 then 500 then 200 | 200 | 3 |
| History policy; 503 then 500 then 200 | 200 | 3 |
| History policy; 503 then 503 then 200 | 503, repeated failure stops retries | 2 |
| No policy; 503 then 503 then 200 | 200 | 3 |
| Allow 503; upstream always returns 503 | 503, Envoy retry limit wins | 3 |
| Allow 503; Envoy runtime retries disabled | 503, Envoy vetoes the proposal | 1 |
| Allow 503; retry circuit breaker set to zero | 503, Envoy vetoes the proposal | 1 |
| Allow with 1.5 s delay; route timeout is 1 s | 504; no later attempt | 1 |
| Allow with 1.5 s delay; client disconnects | Cancelled; no later attempt | 1 |

The smoke test also restores runtime retries, rejects invalid demo policy input,
sends 32 concurrent requests across two workers, and checks request-token cleanup.
The deadline and cancellation cases wait beyond the proposed delay to catch late
attempts. Cancellation must destroy the filter before the route deadline could
mask it.

## Build and run

Requires Python 3.10+, Go 1.25.6+, a C compiler and Envoy's native Bazel build
prerequisites. Build Envoy and the module for the same operating system and
architecture. The first Envoy build is substantial.

Clone the PoC and run:

```bash
git clone https://github.com/dio/envoy-attempt-policy-poc.git
cd envoy-attempt-policy-poc
python3 scripts/prepare.py
bash scripts/build-envoy.sh
bash scripts/build.sh
python3 scripts/smoke.py
```

`envoy-revision.txt` pins the upstream commit. `prepare.py` fetches that commit into
`build/envoy`, verifies the patch digest, and applies `patches/attempt-policy-poc.patch`.
It refuses to overwrite unrelated tracked edits. The Go SDK comes from that same
prepared source tree. No application repository or external service is required.

`envoy-build/` selects the extensions needed by the example and SDK host callbacks.
On Linux the pinned Envoy source selects its hermetic Clang toolchain; on macOS the script uses
the native toolchain and exports dynamic-module callback symbols.

The smoke test allocates loopback ports and starts its own synthetic upstream and
Envoy process. It stops only the processes and server it starts. Generated
configuration, Envoy/module events, and a successful run's JSON summary go to
`build/smoke.yaml`, `build/envoy.log`, and `build/results.json`. The summary records
the binary, module and patch digests. A failed run removes any earlier summary.

To use an independently built copy of this exact patched revision, set
`ENVOY_SOURCE` for the build scripts and `ENVOY_BINARY` for the smoke test. A stock
binary cannot load the module because it lacks the experimental host symbol.

## Validation

The native build and all smoke cases passed on macOS arm64, including the
32-request concurrent history test and request-token cleanup. The
[validation record](validation/macos-arm64.json) contains the tested versions,
artifact digests and observed results. Go vet and clean-source patch application
checks also passed. Upstream C++ sanitizer suites have not been qualified by this PoC.

[Linux qualification](https://github.com/dio/envoy-attempt-policy-poc/actions/workflows/linux.yml)
runs on native Ubuntu amd64 and arm64 runners for code changes and manual dispatch.
It builds the pinned patched Envoy and Go module, runs the same smoke test, then
rebuilds the module with Go's race detector and repeats the integration checks.
Each job uploads result JSON, logs and its CI environment. The Envoy binary cache
is keyed by architecture and all pinned source/patch/build inputs; the module and
smoke tests always run. A queued or running workflow is not a passing qualification.

## Try it manually

```bash
# Terminal 1
python3 scripts/upstream.py

# Terminal 2
ENVOY_DYNAMIC_MODULES_SEARCH_PATH="$PWD/build" \
  ./build/envoy-static -c envoy.yaml --concurrency 2 --disable-hot-restart

# Terminal 3: the upstream starts a new outcome sequence for each unique ID.
curl -i localhost:10000/recover -H 'x-demo-id: first' -H 'x-demo-policy: deny'
curl -i localhost:10000/recover -H 'x-demo-id: second' -H 'x-demo-policy: retry'
curl -i localhost:10000/sequence -H 'x-demo-id: third' -H 'x-demo-policy: selective'
curl -i localhost:10000/sequence -H 'x-demo-id: fourth' -H 'x-demo-policy: history'
curl -i localhost:10000/repeat -H 'x-demo-id: fifth' -H 'x-demo-policy: history'
```

The module consumes and removes `x-demo-policy` before forwarding. This header is
only a loopback demo selector; production policy would come from trusted extension
configuration and validated request context. It does not set Envoy retry-control
headers. `x-demo-id` lets the fixture count attempts for each request.

## Experimental interface

The downstream HTTP filter registers once during request headers. Registration
stores an opaque integer token in request-lifetime filter state. On an upstream
response or supported reset, the router calls the module on its worker thread.
The module returns deny or a proposed delay; the existing retry scheduler can still
reject it. A Go registry retains policy state and removes its token on destruction.
The module remains loaded for process lifetime in this example.

The policy configuration is immutable; the history example records the preceding
observed response in request-local state. Evaluating an outcome does not advance
a routing step or count a proposed retry as dispatched. A `decision` event means
the extension proposed a retry,
not that Envoy accepted or dispatched it. Actual attempts are counted by the
synthetic upstream. The patch also includes an opaque-handle correction for the
pinned Go SDK so C retains C-allocated tokens instead of Go object pointers.

The patch does not change timeout values or timer start semantics. It requires a
route retry policy and overrides its retry-eligibility classification for registered
requests, while retaining Envoy's existing scheduler checks. Unregistered requests
follow the original route path.

## Questions for an upstream design

- Compare this need with route specifiers, retry predicates, filter state and
  supported module callbacks at an explicitly recorded upstream revision.
- Replace the experimental raw C callback address and delay-plus-one encoding
  with a reviewed router interface, typed outcomes and lifecycle-owned bindings.
- Define deny/default/allow precedence and preserve protocol-specific handling.
  This PoC exercises HTTP/1 upstream responses; it does not qualify HTTP/2, HTTP/3,
  early data, gRPC, request-body replay or streaming behavior.
- Define scheduling acceptance, dispatch and terminal notifications before allowing
  extensions to advance routing steps or send budgets. Define duplicate/stale outcome
  handling for history-dependent decisions. Preserve retry accounting explicitly.
- Add a request-registration feature guard and capability discovery. The smoke
  test's `upstream.use_retry` check is an existing Envoy scheduler control, not an
  implementation of the proposed feature guard.
- Define or reject hedging combinations and expand lifecycle/sanitizer coverage.
  The demo config does not enable hedging. This patch is not production-ready.

Request-specific timeout overrides and changes to timer origins are separate
proposals. The useful pattern here is an extension supplying retry decisions while
Envoy continues to own execution.
