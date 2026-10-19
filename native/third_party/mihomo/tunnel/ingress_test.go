package tunnel

import (
	C "github.com/metacubex/mihomo/constant"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestEmbeddingIngressJoinsDescendants(t *testing.T) {
	ResumeIngress()
	if !admitIngress() {
		t.Fatal("new ingress rejected")
	}
	SuspendIngress()
	if admitIngress() {
		t.Fatal("suspended ingress admitted")
	}
	done := make(chan struct{})
	go func() { WaitIngress(); close(done) }()
	childStarted, release := make(chan struct{}), make(chan struct{})
	spawnIngressChild(func() { close(childStarted); <-release })
	ingressLifetime.jobs.Done()
	<-childStarted
	select {
	case <-done:
		t.Fatal("wait returned before admitted child")
	case <-time.After(time.Millisecond):
	}
	close(release)
	<-done
	ResumeIngress()
	if admitLegacyIngress() {
		ingressLifetime.jobs.Done()
		t.Fatal("unversioned legacy queue admitted after lifecycle opt-in")
	}
}

type countedPacket struct{ drops atomic.Int32 }

func (p *countedPacket) Data() []byte { return nil }
func (p *countedPacket) LocalAddr() net.Addr {
	return &net.UDPAddr{IP: net.IPv4(198, 18, 0, 1), Port: 1234}
}
func (p *countedPacket) WriteBack(b []byte, _ net.Addr) (int, error) { return len(b), nil }
func (p *countedPacket) Drop()                                       { p.drops.Add(1) }

func TestPacketSenderCloseDoesNotStrandConcurrentAdmission(t *testing.T) {
	for round := 0; round < 200; round++ {
		s := newPacketSender()
		packets := make([]*countedPacket, 256)
		var wg sync.WaitGroup
		start := make(chan struct{})
		for i := range packets {
			p := &countedPacket{}
			packets[i] = p
			wg.Add(1)
			go func() { defer wg.Done(); <-start; s.Send(C.NewPacketAdapter(p, &C.Metadata{})) }()
		}
		wg.Add(1)
		go func() { defer wg.Done(); <-start; s.Close() }()
		close(start)
		wg.Wait()
		for _, p := range packets {
			if p.drops.Load() != 1 {
				t.Fatalf("packet dropped %d times", p.drops.Load())
			}
		}
	}
}
