// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"github.com/metacubex/mihomo/component/resolver"
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

// Regression stress fixture: production ingress and teardown, unsupported
// HTTP UDP target so there are no external sockets or host VPN operations.
func TestQueuedUDPStopRestart(t *testing.T) {
	cfg := testConfig()
	cfg.LANEnabled = false
	cfg.PhoneVPN = true
	body := []byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A"]}],"rules":["MATCH,A"]}`)
	p, err := sanitizeProfile(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	for j := 0; j < 150; j++ {
		parsed, err := MC.ParseRawConfig(p.raw)
		if err != nil {
			t.Fatal(err)
		}
		if err = installUDPGuards(parsed); err != nil {
			t.Fatal(err)
		}
		executor.ApplyConfig(parsed, true)
		activateRuntime(parsed)
		e, _ := New(cfg)
		e.current = parsed
		boundary := newPhonePacketTunnel(tunnel.Tunnel).(*phonePacketTunnel)
		for i := 0; i < 256; i++ {
			packet := &fixtureUDPPacket{data: []byte("fixture"), source: &net.UDPAddr{IP: net.ParseIP("198.18.0.1"), Port: 54321}, dropped: make(chan struct{})}
			boundary.HandleUDPPacket(packet, &C.Metadata{NetWork: C.UDP, Type: C.TUN, SrcIP: netip.MustParseAddr("198.18.0.1"), SrcPort: 54321, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: uint16(10000 + i)})
		}
		boundary.Close()
		e.cancel()
		e.mu.Lock()
		e.unloadLocked()
		e.mu.Unlock()
	}
}

type blockedPreRuleMapper struct {
	resolver.Enhancer
	entered chan struct{}
	release chan struct{}
	once    sync.Once
}

func (b *blockedPreRuleMapper) MappingEnabled() bool {
	b.once.Do(func() { close(b.entered) })
	<-b.release
	return false
}

// A dial-only barrier cannot observe this admitted operation: it is blocked in
// the upstream metadata stage before adapter selection and before runtime.begin.
func TestIngressDrainWaitsForPreRuleMetadata(t *testing.T) {
	for _, network := range []C.NetWork{C.TCP, C.UDP} {
		t.Run(network.String(), func(t *testing.T) {
			cfg := testConfig()
			cfg.LANEnabled = false
			cfg.PhoneVPN = true
			p, err := sanitizeProfile([]byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A"]}],"rules":["MATCH,A"]}`), cfg)
			if err != nil {
				t.Fatal(err)
			}
			parsed, err := MC.ParseRawConfig(p.raw)
			if err != nil {
				t.Fatal(err)
			}
			if err = installUDPGuards(parsed); err != nil {
				t.Fatal(err)
			}
			executor.ApplyConfig(parsed, true)
			activateRuntime(parsed)
			mapper := &blockedPreRuleMapper{entered: make(chan struct{}), release: make(chan struct{})}
			resolver.DefaultHostMapper = mapper
			m := &C.Metadata{NetWork: network, Type: C.TUN, SrcIP: netip.MustParseAddr("198.18.0.1"), SrcPort: 54321, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: 443}
			if network == C.TCP {
				client, server := net.Pipe()
				defer client.Close()
				go tunnel.Tunnel.HandleTCPConn(server, m)
			} else {
				packet := &fixtureUDPPacket{data: []byte("fixture"), source: &net.UDPAddr{IP: net.ParseIP("198.18.0.1"), Port: 54321}, dropped: make(chan struct{})}
				tunnel.Tunnel.HandleUDPPacket(packet, m)
			}
			select {
			case <-mapper.entered:
			case <-time.After(time.Second):
				t.Fatal("metadata stage not entered")
			}
			e, _ := New(cfg)
			e.current = parsed
			stopped := make(chan struct{})
			go func() { e.cancel(); e.mu.Lock(); e.unloadLocked(); e.mu.Unlock(); close(stopped) }()
			select {
			case <-stopped:
				t.Fatal("unload returned while pre-rule ingress was blocked")
			case <-time.After(20 * time.Millisecond):
			}
			close(mapper.release)
			select {
			case <-stopped:
			case <-time.After(time.Second):
				t.Fatal("unload did not join released ingress")
			}
		})
	}
}
