// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/hub/executor"
	"github.com/metacubex/mihomo/tunnel"
	"net"
	"net/netip"
	"sync"
	"testing"
	"time"
)

type blockedPhoneTCP struct {
	C.Tunnel
	entered   chan struct{}
	cancelled chan struct{}
	release   chan struct{}
}

func (b *blockedPhoneTCP) HandleTCPConn(conn net.Conn, m *C.Metadata) {
	ctx, done, err := phoneTCPContext(context.Background(), m)
	if err != nil {
		return
	}
	defer done()
	close(b.entered)
	<-ctx.Done()
	close(b.cancelled)
	<-b.release
}
func TestPhoneTCPStopCancelsAndJoinsHandler(t *testing.T) {
	upstream := &blockedPhoneTCP{entered: make(chan struct{}), cancelled: make(chan struct{}), release: make(chan struct{})}
	owner := newPhonePacketTunnel(upstream).(*phonePacketTunnel)
	client, server := net.Pipe()
	defer client.Close()
	returned := make(chan struct{})
	go func() {
		owner.HandleTCPConn(server, &C.Metadata{NetWork: C.TCP, Type: C.TUN, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: 443})
		close(returned)
	}()
	mustSignal(t, upstream.entered, "phone TCP dial not admitted")
	stopped := make(chan struct{})
	go func() { owner.Close(); close(stopped) }()
	mustSignal(t, upstream.cancelled, "phone-only stop did not cancel pending TCP dial")
	if _, err := client.Read(make([]byte, 1)); err == nil {
		t.Fatal("phone-only stop did not close inbound TCP")
	}
	select {
	case <-stopped:
		t.Fatal("phone stop returned before TCP handler retired")
	default:
	}
	close(upstream.release)
	mustSignal(t, returned, "TCP handler not retired")
	mustSignal(t, stopped, "phone TCP stop did not finish")
	owner.mu.Lock()
	remaining := len(owner.tcp)
	owner.mu.Unlock()
	if remaining != 0 {
		t.Fatal("phone TCP token retained")
	}
}

type blockedPhoneRule struct {
	C.Rule
	entered, release chan struct{}
	once             sync.Once
}

func (r *blockedPhoneRule) Match(m *C.Metadata, h C.RuleMatchHelper) (bool, string) {
	r.once.Do(func() { close(r.entered) })
	<-r.release
	return r.Rule.Match(m, h)
}

// A deliberately blocked rule proves that pending pre-dial matching is joined,
// including sender saturation. This relies on the verified pinned derivative's
// serialized sender Send/Close plus explicitly tracked upstream child jobs.
func TestPhoneQueuedUDPSaturatedRuleStopRestart(t *testing.T) {
	cfg := testConfig()
	cfg.LANEnabled = false
	cfg.PhoneVPN = true
	body := []byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A"]}],"rules":["MATCH,A"]}`)
	p, err := sanitizeProfile(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	for generation := 0; generation < 3; generation++ {
		parsed, err := MC.ParseRawConfig(p.raw)
		if err != nil {
			t.Fatal(err)
		}
		block := &blockedPhoneRule{Rule: parsed.Rules[0], entered: make(chan struct{}), release: make(chan struct{})}
		parsed.Rules[0] = block
		if err = installUDPGuards(parsed); err != nil {
			t.Fatal(err)
		}
		executor.ApplyConfig(parsed, true)
		activateRuntime(parsed)
		e, _ := New(cfg)
		e.current = parsed
		owner := newPhonePacketTunnel(tunnel.Tunnel).(*phonePacketTunnel)
		source := &net.UDPAddr{IP: net.ParseIP("198.18.0.1"), Port: 53001}
		send := func() {
			packet := &fixtureUDPPacket{data: []byte("fixture"), source: source, dropped: make(chan struct{})}
			owner.HandleUDPPacket(packet, &C.Metadata{NetWork: C.UDP, Type: C.TUN, SrcIP: netip.MustParseAddr("198.18.0.1"), SrcPort: 53001, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: 443})
		}
		send()
		mustSignal(t, block.entered, "blocked rule never entered")
		for i := 0; i < 2048; i++ {
			send()
		}
		stopped := make(chan struct{})
		go func() { owner.Close(); close(stopped) }()
		deadline := time.Now().Add(time.Second)
		for {
			owner.mu.Lock()
			closed := owner.closed
			owner.mu.Unlock()
			if closed {
				break
			}
			if time.Now().After(deadline) {
				t.Fatal("phone close did not start")
			}
			time.Sleep(time.Millisecond)
		}
		select {
		case <-stopped:
			t.Fatal("stop escaped blocked pre-dial rule")
		default:
		}
		close(block.release)
		mustSignal(t, stopped, "saturated phone UDP failed to drain")
		e.cancel()
		e.mu.Lock()
		e.unloadLocked()
		e.mu.Unlock()
	}
}
