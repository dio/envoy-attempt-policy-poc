package main

/*
#include <stdint.h>
extern uint64_t attemptDecision(uint64_t token, uint32_t reason, uint32_t status);
static uintptr_t attempt_decision_address(void) {
    return (uintptr_t)&attemptDecision;
}
*/
import "C"

import (
	"encoding/json"
	"os"
	"sync"
	"sync/atomic"

	"github.com/dio/envoy-attempt-policy-poc/internal/policy"
	sdk "github.com/envoyproxy/envoy/source/extensions/dynamic_modules/sdk/go"
	_ "github.com/envoyproxy/envoy/source/extensions/dynamic_modules/sdk/go/abi"
	"github.com/envoyproxy/envoy/source/extensions/dynamic_modules/sdk/go/shared"
)

var nextToken atomic.Uint64
var requests sync.Map
var eventMu sync.Mutex

type requestPolicy struct {
	policy     policy.Policy
	id         string
	decisions  atomic.Uint64
	lastStatus atomic.Uint32
}

func event(fields map[string]any) {
	eventMu.Lock()
	defer eventMu.Unlock()
	// stderr is captured by the smoke test. Logging is demo instrumentation.
	_ = json.NewEncoder(os.Stderr).Encode(fields)
}

//export attemptDecision
func attemptDecision(token C.uint64_t, reason C.uint32_t, status C.uint32_t) C.uint64_t {
	value, exists := requests.Load(uint64(token))
	if !exists {
		return 0
	}
	request, ok := value.(*requestPolicy)
	if !ok {
		return 0
	}
	// Remember an observed response, not an assumed scheduling or dispatch event.
	// The experimental router invokes this once per response, on the worker.
	previousStatus := request.lastStatus.Load()
	if reason == 0 {
		previousStatus = request.lastStatus.Swap(uint32(status))
	}
	allow, delay := request.policy.Decide(uint32(reason), uint32(status), previousStatus)
	event(map[string]any{
		"event": "decision", "id": request.id, "policy": request.policy.Name,
		"outcome": uint32(reason), "status": uint32(status), "allow": allow,
		"delay_ms": delay.Milliseconds(), "decision_number": request.decisions.Add(1),
		"previous_status": previousStatus,
	})
	if !allow {
		return 0
	}
	// This encoding belongs to the experimental patch, not a stable API.
	return C.uint64_t(delay.Milliseconds() + 1)
}

func init() {
	sdk.RegisterHttpFilterConfigFactories(map[string]shared.HttpFilterConfigFactory{
		"attempt_policy": &configFactory{},
	})
}

func main() {}

type configFactory struct {
	shared.EmptyHttpFilterConfigFactory
}

func (*configFactory) Create(shared.HttpFilterConfigHandle, []byte) (shared.HttpFilterFactory, error) {
	return &filterFactory{}, nil
}

type filterFactory struct{ shared.EmptyHttpFilterFactory }

func (*filterFactory) Create(handle shared.HttpFilterHandle) shared.HttpFilter {
	return &filter{handle: handle}
}

type registrar interface {
	SetRouterAttemptPolicyPoC(token uint64, callback uintptr) bool
}

type filter struct {
	shared.EmptyHttpFilter
	handle shared.HttpFilterHandle
	token  uint64
}

func (f *filter) OnRequestHeaders(headers shared.HeaderMap, _ bool) shared.HeadersStatus {
	name := headers.GetOne("x-demo-policy").ToString()
	id := headers.GetOne("x-demo-id").ToString()
	headers.Remove("x-demo-policy")
	if name == "" || name == "default" {
		return shared.HeadersStatusContinue
	}
	selected, valid := policy.Select(name)
	if !valid {
		f.reply(400, "unknown demo policy")
		return shared.HeadersStatusStop
	}
	host, supported := f.handle.(registrar)
	if !supported {
		f.reply(503, "attempt policy unavailable")
		return shared.HeadersStatusStop
	}
	f.token = nextToken.Add(1)
	requests.Store(f.token, &requestPolicy{policy: selected, id: id})
	if !host.SetRouterAttemptPolicyPoC(f.token, uintptr(C.attempt_decision_address())) {
		requests.Delete(f.token)
		f.token = 0
		f.reply(503, "attempt policy registration rejected")
		return shared.HeadersStatusStop
	}
	event(map[string]any{"event": "registered", "id": id, "policy": name})
	return shared.HeadersStatusContinue
}

func (f *filter) reply(status uint32, message string) {
	f.handle.SendLocalResponse(
		status,
		[][2]string{{"content-type", "text/plain"}},
		[]byte(message+"\n"),
		"attempt_policy_poc",
	)
}

func (f *filter) OnDestroy() {
	if f.token == 0 {
		return
	}
	value, exists := requests.LoadAndDelete(f.token)
	if !exists {
		return
	}
	request, ok := value.(*requestPolicy)
	if ok {
		event(map[string]any{"event": "destroyed", "id": request.id})
	}
}
