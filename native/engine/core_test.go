// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"errors"
	C "github.com/metacubex/mihomo/constant"
	"net"
	"net/netip"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type fakeNode struct {
	C.Proxy
	name   string
	closed atomic.Int32
	dial   func(context.Context, *C.Metadata) (C.Conn, error)
}

func (n *fakeNode) Name() string { return n.name }
func (n *fakeNode) Close() error { n.closed.Add(1); return nil }
func (n *fakeNode) DialContext(ctx context.Context, m *C.Metadata) (C.Conn, error) {
	if n.dial != nil {
		return n.dial(ctx, m)
	}
	return nil, errors.New("fixture refused")
}
func TestParseSupportedNodesDataOnly(t *testing.T) {
	raw := []byte("proxies:\n- name: Hong Kong 1\n  type: socks5\n  server: 8.8.8.8\n  port: 1080\n- name: Unsafe Direct\n  type: direct\nlisteners: [{name: bad, type: tun}]\nrules: [MATCH,DIRECT]\n")
	nodes, err := parseNodes(raw)
	if err != nil {
		t.Fatal(err)
	}
	defer closeNodes(nodes)
	if len(nodes) != 1 || nodes[0].proxy.Name() != "Hong Kong 1" {
		t.Fatal("unsupported node or config was imported")
	}
	for _, line := range []string{"name: DIRECT", "name: ' x'", "name: Hong Kong 1\n  dialer-proxy: DIRECT", "name: Hong Kong 1\n  private-key: /etc/passwd", "name: Hong Kong 1\n  interface-name: eth0"} {
		raw := []byte("proxies:\n- " + line + "\n  type: socks5\n  server: 8.8.8.8\n  port: 1080\n")
		if nodes, err := parseNodes(raw); err == nil {
			closeNodes(nodes)
			t.Fatalf("accepted unsafe node %s", line)
		}
	}
	if nodes, err := parseNodes([]byte("proxies: [{name: node, type: socks5, server: 127.0.0.1, port: 80}]")); err == nil {
		closeNodes(nodes)
		t.Fatal("accepted loopback upstream")
	}
}
func TestNodeOrder(t *testing.T) {
	nodes := []*node{{proxy: &fakeNode{name: "Other"}}, {proxy: &fakeNode{name: "Japan"}}, {proxy: &fakeNode{name: "Hong Kong"}}, {proxy: &fakeNode{name: "Preferred"}}}
	cfg := validConfig()
	orderNodes(nodes, cfg)
	if nodes[0].proxy.Name() != "Hong Kong" || nodes[1].proxy.Name() != "Japan" {
		t.Fatal("region priority missing")
	}
	cfg.SelectionMode = "prefer"
	cfg.PreferredNode = "Preferred"
	orderNodes(nodes, cfg)
	if nodes[0].proxy.Name() != "Preferred" {
		t.Fatal("preferred node not first")
	}
}
func TestCoreIdleAndActiveLease(t *testing.T) {
	cfg := validConfig()
	cfg.IdleSeconds = 1
	c := newEmbeddedCore(cfg)
	defer c.Close()
	n := &fakeNode{name: "node"}
	c.mu.Lock()
	c.nodes = []*node{{proxy: n, healthy: true}}
	c.state = "running"
	c.lastUsed = time.Now().Add(-time.Minute)
	c.mu.Unlock()
	if _, err := c.Acquire(context.Background()); err != nil {
		t.Fatal(err)
	}
	time.Sleep(1200 * time.Millisecond)
	if n.closed.Load() != 0 {
		t.Fatal("active node closed")
	}
	c.Release()
	deadline := time.Now().Add(2500 * time.Millisecond)
	for n.closed.Load() == 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if n.closed.Load() != 1 {
		t.Fatal("idle node not closed exactly once")
	}
}
func TestExternalNeverFallsBackDirect(t *testing.T) {
	cfg := validConfig()
	cfg.SelectionMode = "fixed"
	cfg.PreferredNode = "chosen"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	count := 0
	chosen := &fakeNode{name: "chosen", dial: func(ctx context.Context, m *C.Metadata) (C.Conn, error) {
		count++
		if m.Host != "" || m.DstIP != netip.MustParseAddr("8.8.8.8") {
			t.Fatal("destination not pinned")
		}
		return nil, errors.New("down")
	}}
	c.nodes = []*node{{proxy: chosen, healthy: true}, {proxy: &fakeNode{name: "other", dial: func(context.Context, *C.Metadata) (C.Conn, error) {
		t.Fatal("fixed mode fallback attempted")
		return nil, nil
	}}, healthy: true}}
	if conn, err := c.DialExternal(context.Background(), "8.8.8.8", 443); err == nil || conn != nil {
		t.Fatal("failed open")
	}
	if count != 1 {
		t.Fatal("chosen not attempted")
	}
	if _, err := c.DialExternal(context.Background(), "127.0.0.1", 443); err == nil {
		t.Fatal("loopback accepted")
	}
}
func TestPublicAddressDenials(t *testing.T) {
	for _, host := range []string{"127.0.0.1", "10.1.2.3", "::1", "::ffff:8.8.8.8", "localhost", "169.254.169.254", "2001:db8::1"} {
		if _, err := publicAddresses(context.Background(), host); err == nil {
			t.Fatalf("accepted %s", host)
		}
	}
	if ips, err := publicAddresses(context.Background(), "8.8.8.8"); err != nil || len(ips) != 1 {
		t.Fatalf("public literal denied: %v", err)
	}
}
func TestClosedCoreCannotAcquire(t *testing.T) {
	c := newEmbeddedCore(validConfig())
	c.Close()
	if _, err := c.Acquire(context.Background()); err == nil {
		t.Fatal("acquired closed core")
	}
	if strings.Contains(c.Status()["error"].(string), "https://") {
		t.Fatal("status leaked URL")
	}
}

func TestHealthDoesNotResetIdleDeadline(t *testing.T) {
	cfg := validConfig()
	cfg.IdleSeconds = 2
	cfg.HealthInterval = 1
	cfg.HealthURL = "https://8.8.8.8/"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	n := &fakeNode{name: "node"}
	c.mu.Lock()
	c.nodes = []*node{{proxy: n, healthy: true}}
	c.state = "running"
	original := time.Now()
	c.lastUsed = original
	c.mu.Unlock()
	deadline := time.Now().Add(3500 * time.Millisecond)
	for n.closed.Load() == 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if n.closed.Load() != 1 {
		t.Fatal("health checks prevented idle shutdown")
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.lastUsed.Equal(original) {
		t.Fatal("health probe updated client activity time")
	}
}

func TestPublicDNSFailClosed(t *testing.T) {
	tests := []struct {
		name    string
		ips     []net.IPAddr
		err     error
		allowed bool
	}{
		{"A", []net.IPAddr{{IP: net.IP{8, 8, 8, 8}}}, nil, true},
		{"mappedAAAAorAmbiguousHostsAlias", []net.IPAddr{{IP: net.ParseIP("8.8.8.8")}}, nil, false},
		{"AAAA", []net.IPAddr{{IP: net.ParseIP("2606:4700:4700::1111")}}, nil, true},
		{"privateMixed", []net.IPAddr{{IP: net.IP{8, 8, 8, 8}}, {IP: net.IP{10, 1, 2, 3}}}, nil, false},
		{"loopbackMixed", []net.IPAddr{{IP: net.IP{8, 8, 8, 8}}, {IP: net.IP{127, 0, 0, 1}}}, nil, false},
		{"partialError", []net.IPAddr{{IP: net.IP{8, 8, 8, 8}}}, errors.New("partial DNS failure"), false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := &fakeResolver{answers: tt.ips, err: tt.err}
			_, err := publicAddressesWithResolver(context.Background(), r, "example.com")
			if (err == nil) != tt.allowed {
				t.Fatalf("allowed=%v err=%v", tt.allowed, err)
			}
		})
	}
}

func TestLocalSubscriptionSnapshot(t *testing.T) {
	path := t.TempDir() + "/provider.yaml"
	body := []byte("proxies: [{name: fixture, type: socks5, server: 8.8.8.8, port: 1080}]")
	if err := os.WriteFile(path, body, 0600); err != nil {
		t.Fatal(err)
	}
	got, err := readSubscriptionFile(context.Background(), path)
	if err != nil || string(got) != string(body) {
		t.Fatalf("read failed %v", err)
	}
	if _, err := readSubscriptionFile(context.Background(), t.TempDir()); err == nil {
		t.Fatal("directory accepted")
	}
	if err := os.WriteFile(path, nil, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readSubscriptionFile(context.Background(), path); err == nil {
		t.Fatal("empty file accepted")
	}
	cfg := validConfig()
	cfg.SubscriptionURL = ""
	cfg.SubscriptionFile = path
	if err := cfg.Validate(); err != nil {
		t.Fatal(err)
	}
	cfg.SubscriptionURL = "https://provider.example/sub"
	if cfg.Validate() == nil {
		t.Fatal("both subscription sources accepted")
	}
}

func TestSlowHealthCannotHoldPoolPastIdle(t *testing.T) {
	cfg := validConfig()
	cfg.IdleSeconds = 2
	cfg.HealthInterval = 1
	cfg.HealthTimeout = 60000
	cfg.HealthURL = "https://8.8.8.8/"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	n := &fakeNode{name: "slow", dial: func(ctx context.Context, _ *C.Metadata) (C.Conn, error) { <-ctx.Done(); return nil, ctx.Err() }}
	c.mu.Lock()
	c.nodes = []*node{{proxy: n, healthy: true}}
	c.state = "running"
	c.lastUsed = time.Now()
	c.mu.Unlock()
	deadline := time.Now().Add(3500 * time.Millisecond)
	for n.closed.Load() == 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if n.closed.Load() != 1 {
		t.Fatal("slow maintenance health probe held idle core alive")
	}
}
