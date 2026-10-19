package tunnel

import "sync"

// ingressLifetime makes the asynchronous tunnel quiescent before an embedding
// application replaces process-global configuration. Normal Mihomo execution
// keeps admission open and is otherwise unchanged.
var ingressLifetime = struct {
	sync.Mutex
	accepting     bool
	legacyBlocked bool
	jobs          sync.WaitGroup
}{accepting: true}

func admitIngress() bool {
	ingressLifetime.Lock()
	defer ingressLifetime.Unlock()
	if !ingressLifetime.accepting {
		return false
	}
	ingressLifetime.jobs.Add(1)
	return true
}

func admitLegacyIngress() bool {
	ingressLifetime.Lock()
	defer ingressLifetime.Unlock()
	if !ingressLifetime.accepting || ingressLifetime.legacyBlocked {
		return false
	}
	ingressLifetime.jobs.Add(1)
	return true
}

// A child is registered while its admitted parent is still alive. Therefore
// WaitIngress cannot observe zero before all descendants have been registered.
func spawnIngressChild(work func()) {
	ingressLifetime.jobs.Add(1)
	go func() { defer ingressLifetime.jobs.Done(); work() }()
}

// SuspendIngress rejects new TCP and UDP admission. An embedder must next
// cancel pending dials and close its owned stream/packet connections, then call
// WaitIngress before mutating resolver, rule, mode or proxy globals.
func SuspendIngress() {
	ingressLifetime.Lock()
	ingressLifetime.accepting = false
	ingressLifetime.legacyBlocked = true
	ingressLifetime.Unlock()
}

// WaitIngress joins queued work and every UDP resolve, sender and reader child.
// Admission must remain suspended until this call returns.
func WaitIngress() { ingressLifetime.jobs.Wait() }

// ResumeIngress admits a newly configured generation. Call only after the
// previous generation was suspended, closed and completely joined. Lifecycle
// management permanently rejects the deprecated raw TCPIn/UDPIn queues: those
// unversioned channel APIs cannot identify a submission from an old generation.
func ResumeIngress() {
	ingressLifetime.Lock()
	ingressLifetime.accepting = true
	ingressLifetime.legacyBlocked = true
	ingressLifetime.Unlock()
}

func runTCPIngress(work func(), reject func()) {
	if !admitIngress() {
		reject()
		return
	}
	defer ingressLifetime.jobs.Done()
	work()
}
