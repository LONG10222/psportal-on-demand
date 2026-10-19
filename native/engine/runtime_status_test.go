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

// A successful receive shutdown need not cancel an already-issued async read
// on every platform. Model that behavior independently of the host OS.
type pendingReadShutdownConn struct {
	net.Conn
	reading chan struct{}
	once    sync.Once
}

func (c *pendingReadShutdownConn) Read(data []byte) (int, error) {
	c.once.Do(func() { close(c.reading) })
	return c.Conn.Read(data)
}
func (c *pendingReadShutdownConn) CloseRead() error { return nil }

func TestUpstreamEOFInterruptsPendingUploadRead(t *testing.T) {
	clientSide, clientPeer := net.Pipe()
	defer clientSide.Close()
	defer clientPeer.Close()
	underlying := &pendingReadShutdownConn{Conn: clientSide, reading: make(chan struct{})}
	client := &timedConn{Conn: underlying, timeout: time.Minute}
	upstream, upstreamPeer := net.Pipe()
	defer upstream.Close()
	defer upstreamPeer.Close()
	done := make(chan error, 1)
	go func() {
		done <- duplex(client, upstream, func() error {
			_, err := client.Read(make([]byte, 1))
			return err
		}, func() error {
			<-underlying.reading
			return nil // Upstream EOF while upload read is still pending.
		})
	}()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("upstream EOF left upload read blocked on its idle timeout")
	}
	// Stopping upload must preserve writes for a final error response.
	written := make(chan error, 1)
	go func() { _, err := client.Write([]byte("ok")); written <- err }()
	if err := clientPeer.SetReadDeadline(time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	response := make([]byte, 2)
	if _, err := io.ReadFull(clientPeer, response); err != nil || string(response) != "ok" {
		t.Fatal(string(response), err)
	}
	if err := <-written; err != nil {
		t.Fatal(err)
	}
}

// Delay an in-flight Read's deadline update until after CloseRead has returned.
// Without sticky read cancellation it can revive the socket's idle timeout.
type delayedReadDeadlineConn struct {
	*pendingReadShutdownConn
	setting      chan struct{}
	resume       chan struct{}
	deadlineOnce sync.Once
}

func (c *delayedReadDeadlineConn) SetReadDeadline(deadline time.Time) error {
	if deadline.After(time.Now()) {
		c.deadlineOnce.Do(func() {
			close(c.setting)
			<-c.resume
		})
	}
	return c.Conn.SetReadDeadline(deadline)
}

func TestReadCannotRestoreDeadlineAfterCloseRead(t *testing.T) {
	local, peer := net.Pipe()
	defer local.Close()
	defer peer.Close()
	underlying := &delayedReadDeadlineConn{
		pendingReadShutdownConn: &pendingReadShutdownConn{Conn: local, reading: make(chan struct{})},
		setting:                 make(chan struct{}), resume: make(chan struct{}),
	}
	var resumeOnce sync.Once
	resume := func() { resumeOnce.Do(func() { close(underlying.resume) }) }
	defer resume()
	client := &timedConn{Conn: underlying, timeout: time.Minute}
	done := make(chan error, 1)
	go func() { _, err := client.Read(make([]byte, 1)); done <- err }()
	select {
	case <-underlying.setting:
	case <-time.After(time.Second):
		t.Fatal("read did not begin its deadline refresh")
	}
	if err := client.CloseRead(); err != nil {
		t.Fatal(err)
	}
	resume()
	select {
	case err := <-done:
		if !errors.Is(err, net.ErrClosed) {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("read restored its idle timeout after CloseRead")
	}
	if _, err := client.Read(make([]byte, 1)); !errors.Is(err, net.ErrClosed) {
		t.Fatal(err)
	}
}
