// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"reflect"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"
)

func awaitProxyStatus(t *testing.T, p *Proxy, expectedClients int, expectedConnections uint64) map[string]any {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for {
		status := p.Status()
		if status["connected_clients"] == expectedClients && status["active_connections"] == expectedConnections {
			return status
		}
		if time.Now().After(deadline) {
			t.Fatalf("wrong client metrics: %v", status)
		}
		time.Sleep(time.Millisecond)
	}
}

func TestConnectedClientsAreDistinctAcceptedIPs(t *testing.T) {
	p := startTestProxy(t, &fixtureCore{}, func(p *Proxy) {
		p.cfg.AllowedClients = []string{"127.0.0.1", "127.0.0.2"}
		p.timeout = 5 * time.Second
	})
	first, second := proxyConnect(t, p), proxyConnect(t, p)
	defer first.Close()
	defer second.Close()
	s := awaitProxyStatus(t, p, 1, 2)
	if !reflect.DeepEqual(s["client_ips"], []string{"127.0.0.1"}) {
		t.Fatal(s)
	}
	t.Run("optional_second_loopback_IP", func(t *testing.T) {
		dialer := net.Dialer{LocalAddr: &net.TCPAddr{IP: net.ParseIP("127.0.0.2")}, Timeout: time.Second}
		third, err := dialer.Dial("tcp4", p.Status()["listen_address"].(string))
		if errors.Is(err, syscall.EADDRNOTAVAIL) {
			t.Skip("OS does not expose a second loopback source address")
		}
		if err != nil {
			t.Fatal(err)
		}
		defer third.Close()
		s := awaitProxyStatus(t, p, 2, 3)
		if !reflect.DeepEqual(s["client_ips"], []string{"127.0.0.1", "127.0.0.2"}) {
			t.Fatal(s)
		}
		third.Close()
		awaitProxyStatus(t, p, 1, 2)
	})
	// This real single-IP/multiple-socket assertion is mandatory on every OS.
	first.Close()
	awaitProxyStatus(t, p, 1, 1)
	second.Close()
	awaitProxyStatus(t, p, 0, 0)
}

func TestRejectedClientsDoNotAppearInMetrics(t *testing.T) {
	p := startTestProxy(t, &fixtureCore{}, func(p *Proxy) { p.cfg.AllowedClients = []string{"192.168.1.42"} })
	client := proxyConnect(t, p)
	defer client.Close()
	_, _ = io.ReadAll(client)
	s := awaitProxyStatus(t, p, 0, 0)
	if s["denied_clients"] != uint64(1) || len(s["client_ips"].([]string)) != 0 {
		t.Fatal(s)
	}
}

type wakingFixtureCore struct {
	fixtureCore
	entered chan struct{}
	release chan struct{}
	once    sync.Once
}

func (c *wakingFixtureCore) Acquire(ctx context.Context) (string, error) {
	c.once.Do(func() { close(c.entered) })
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case <-c.release:
	}
	return c.fixtureCore.Acquire(ctx)
}

func TestWakingForwardingAndListenerStatus(t *testing.T) {
	upstreamClosed := make(chan struct{})
	var closeOnce sync.Once
	closeUpstream := func() { closeOnce.Do(func() { close(upstreamClosed) }) }
	defer closeUpstream()
	endpoint := fixture(t, func(conn net.Conn) {
		if _, err := readHeader(bufio.NewReader(conn)); err != nil {
			return
		}
		_, _ = io.WriteString(conn, "HTTP/1.1 200 Connection Established\r\n\r\n")
		<-upstreamClosed
	})
	core := &wakingFixtureCore{fixtureCore: fixtureCore{endpoint: endpoint}, entered: make(chan struct{}), release: make(chan struct{})}
	p := startTestProxy(t, core, nil)
	c := newEmbeddedCore(validConfig())
	defer c.Close()
	e := &Engine{cfg: p.cfg, proxy: p, core: c, running: true}
	state := func() map[string]any {
		var s map[string]any
		if err := json.Unmarshal([]byte(e.Status()), &s); err != nil {
			t.Fatal(err)
		}
		return s
	}
	if s := state(); s["state"] != "listening" || s["core_state"] != "stopped" || s["address"] == "" {
		t.Fatal(s)
	}
	client := proxyConnect(t, p)
	defer client.Close()
	_, _ = io.WriteString(client, "CONNECT 8.8.8.8:443 HTTP/1.1\r\nHost: 8.8.8.8:443\r\n\r\n")
	select {
	case <-core.entered:
	case <-time.After(time.Second):
		t.Fatal("core not waking")
	}
	if s := state(); s["state"] != "waking" || s["connected_clients"] != float64(1) {
		t.Fatal(s)
	}
	close(core.release)
	if _, err := readHeader(bufio.NewReader(client)); err != nil {
		t.Fatal(err)
	}
	if s := state(); s["state"] != "forwarding" || s["active_connections"] != float64(1) {
		t.Fatal(s)
	}
	closeUpstream()
	_, _ = io.Copy(io.Discard, client)
	awaitProxyStatus(t, p, 0, 0)
	if s := state(); s["state"] != "listening" {
		t.Fatal(s)
	}
}

func TestMaximumNodePoolStatusFitsOneMiB(t *testing.T) {
	for _, part := range []string{"<>&", `"\`, "\u2028"} {
		cfg := validConfig()
		c := newEmbeddedCore(cfg)
		c.mu.Lock()
		for i := 0; i < 1000; i++ {
			name := fmt.Sprintf("%04d", i) + strings.Repeat(part, (256-5)/len(part)) + "a"
			if !validNodeName(name) {
				t.Fatal("invalid fixture name")
			}
			c.nodes = append(c.nodes, measuredNode(name, 0))
		}
		c.mu.Unlock()
		e := &Engine{cfg: cfg, core: c, running: true}
		raw := e.Status()
		c.Close()
		if len(raw) >= 1024*1024 {
			t.Fatalf("valid node pool exceeded1MiB: %d", len(raw))
		}
		var status map[string]any
		if err := json.Unmarshal([]byte(raw), &status); err != nil || len(status["nodes"].([]any)) != 1000 {
			t.Fatal("pool truncated", err)
		}
		if strings.Contains(raw, `\u003c`) || strings.Contains(raw, `\u003e`) || strings.Contains(raw, `\u0026`) {
			t.Fatal("IPC HTML escaping expanded status")
		}
	}
	if validNodeName(string([]byte{0xff})) {
		t.Fatal("invalid UTF-8 node name accepted")
	}
}
