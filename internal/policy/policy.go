// Package policy contains the demo's immutable request-scoped retry decisions.
package policy

import "time"

// Policy is chosen once when the request enters the HTTP filter.
type Policy struct {
	Name  string
	Delay time.Duration
}

// Select maps demo input to trusted policy. Production extensions would use
// their own validated request context instead of this loopback-only selector.
func Select(name string) (Policy, bool) {
	switch name {
	case "deny":
		return Policy{Name: name}, true
	case "retry", "selective", "history":
		return Policy{Name: name, Delay: 150 * time.Millisecond}, true
	case "slow":
		return Policy{Name: name, Delay: 1500 * time.Millisecond}, true
	default:
		return Policy{}, false
	}
}

// Decide evaluates an outcome without consuming policy progress. The prototype
// has no scheduling-accepted callback, so this policy deliberately stays pure.
func (p Policy) Decide(reason, status, previousStatus uint32) (bool, time.Duration) {
	if p.Name == "deny" {
		return false, 0
	}
	// Prototype reasons: 0 HTTP response, 1 connection failure, 2 remote reset,
	// 3 per-try timeout. The demo exercises HTTP responses only.
	if reason != 0 {
		return false, 0
	}
	if p.Name == "history" {
		eligible := status == 500 || status == 503
		if !eligible || status == previousStatus {
			return false, 0
		}
		return true, p.Delay
	}
	if status != 503 {
		return false, 0
	}
	return true, p.Delay
}
