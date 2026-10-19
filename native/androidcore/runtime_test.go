// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"github.com/metacubex/mihomo/adapter"
	"github.com/metacubex/mihomo/adapter/outbound"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/hub/executor"
	"net"
	"net/netip"
	"sync/atomic"
	"testing"
	"time"
)

type blockingDialAdapter struct {
	*outbound.Direct
	started chan struct{}
	calls   atomic.Int32
}

func (a *blockingDialAdapter) DialContext(ctx context.Context, m *C.Metadata) (C.Conn, error) {
	if a.calls.Add(1) == 1 {
		close(a.started)
	}
	<-ctx.Done()
	return nil, ctx.Err()
}
func TestStopCancelsInFlightCoreDialAndRejectsStaleCallbacks(t *testing.T) {
	cfg := testConfig()
	cfg.LANEnabled = false
	cfg.PhoneVPN = true
	e, _ := New(cfg)
	if err := e.Start(); err != nil {
		t.Fatal(err)
	}
	body := []byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A"]}],"rules":["MATCH,A"]}`)
	p, err := sanitizeProfile(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := MC.ParseRawConfig(p.raw)
	if err != nil {
		t.Fatal(err)
	}
	blocked := &blockingDialAdapter{Direct: outbound.NewDirectWithOption(outbound.DirectOption{Name: "A"}), started: make(chan struct{})}
	parsed.Proxies["A"].(*adapter.Proxy).ProxyAdapter = blocked
	if err = installUDPGuards(parsed); err != nil {
		t.Fatal(err)
	}
	executor.ApplyConfig(parsed, true)
	activateRuntime(parsed)
	e.mu.Lock()
	e.current = parsed
	e.profile = p
	e.mu.Unlock()
	conn, err := e.openTunnel(context.Background(), &C.Metadata{NetWork: C.TCP, Type: C.HTTP, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: 443})
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	select {
	case <-blocked.started:
	case <-time.After(time.Second):
		t.Fatal("controlled dial not entered")
	}
	done := make(chan struct{})
	go func() { e.Stop(); close(done) }()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Stop did not cancel and join in-flight core dial")
	}
	old := parsed.Proxies["A"]
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if _, err := old.DialContext(ctx, &C.Metadata{NetWork: C.TCP, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: 443}); err == nil {
		t.Fatal("late callback dial accepted")
	}
	if blocked.calls.Load() != 1 {
		t.Fatal("stale callback reached retired adapter")
	}
	next, _ := New(cfg)
	if err = next.Start(); err != nil {
		t.Fatal(err)
	}
	next.Stop()
}

type pipeDialAdapter struct {
	*outbound.Direct
	conn net.Conn
}

func (a *pipeDialAdapter) DialContext(context.Context, *C.Metadata) (C.Conn, error) {
	return outbound.NewConn(a.conn, a), nil
}
func TestRuntimeClosesOwnedConnections(t *testing.T) {
	local, remote := net.Pipe()
	defer remote.Close()
	r := newProxyRuntime()
	r.readyOnce.Do(func() { close(r.ready) })
	g := &udpFailClosed{ProxyAdapter: &pipeDialAdapter{Direct: outbound.NewDirect(), conn: local}, runtime: r}
	conn, err := g.DialContext(context.Background(), &C.Metadata{})
	if err != nil {
		t.Fatal(err)
	}
	r.close()
	remote.SetReadDeadline(time.Now().Add(time.Second))
	if _, err := remote.Read(make([]byte, 1)); err == nil {
		t.Fatal("retired runtime left TCP connection open")
	}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}
	r.mu.Lock()
	count := len(r.connections)
	r.mu.Unlock()
	if count != 0 {
		t.Fatalf("runtime retained %d sockets", count)
	}
}
