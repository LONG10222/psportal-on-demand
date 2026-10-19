// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"bytes"
	"context"
	"fmt"
	"github.com/metacubex/mihomo/adapter"
	"github.com/metacubex/mihomo/adapter/outbound"
	"github.com/metacubex/mihomo/component/dialer"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/hub/executor"
	"github.com/metacubex/mihomo/tunnel"
	"io"
	"net"
	"net/netip"
	"strconv"
	"sync"
	"testing"
	"time"
)

type fixtureUDPAdapter struct {
	*outbound.Direct
	target net.Addr
	label  string
}

func (a *fixtureUDPAdapter) ListenPacketContext(ctx context.Context, m *C.Metadata) (C.PacketConn, error) {
	pc, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		return nil, err
	}
	return outbound.NewPacketConn(&fixturePacketConn{PacketConn: pc, target: a.target, label: a.label}, a), nil
}

type fixturePacketConn struct {
	net.PacketConn
	target net.Addr
	label  string
}

func (p *fixturePacketConn) WriteTo(b []byte, _ net.Addr) (int, error) {
	_, err := p.PacketConn.WriteTo(append([]byte(p.label+":"), b...), p.target)
	return len(b), err
}

type fixtureUDPPacket struct {
	data    []byte
	source  net.Addr
	dropped chan struct{}
	once    sync.Once
}

func (p *fixtureUDPPacket) Data() []byte                                { return p.data }
func (p *fixtureUDPPacket) LocalAddr() net.Addr                         { return p.source }
func (p *fixtureUDPPacket) Drop()                                       { p.once.Do(func() { close(p.dropped) }) }
func (p *fixtureUDPPacket) WriteBack(b []byte, _ net.Addr) (int, error) { return len(b), nil }

// Only transport endpoints are redirected to a local receiver; actual Mihomo
// rule matching, proxy wrappers, NAT, packet sender and the production phone
// boundary execute unchanged. No public UDP packets or host TUN are created.
func TestRealUDPRoutingAndDestinationIsolation(t *testing.T) {
	receiver, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer receiver.Close()
	captured := make(chan string, 20)
	go func() {
		buf := make([]byte, 2048)
		for {
			n, _, err := receiver.ReadFrom(buf)
			if err != nil {
				return
			}
			captured <- string(buf[:n])
		}
	}()
	cfg := testConfig()
	body := []byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A"]}],"rules":["IP-CIDR,8.8.8.8/32,DIRECT,no-resolve","MATCH,A"]}`)
	p, err := sanitizeProfile(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := MC.ParseRawConfig(p.raw)
	if err != nil {
		t.Fatal(err)
	}
	// A starts as a genuinely unsupported-UDP HTTP adapter; DIRECT's test-only
	// transport sends to the local capture rather than a public destination.
	parsed.Proxies["DIRECT"].(*adapter.Proxy).ProxyAdapter = &fixtureUDPAdapter{Direct: outbound.NewDirect(), target: receiver.LocalAddr(), label: "direct"}
	if err := installUDPGuards(parsed); err != nil {
		t.Fatal(err)
	}
	executor.ApplyConfig(parsed, true)
	activateRuntime(parsed)
	defer func() {
		retireTestCore(parsed)
	}()
	boundary := newPhonePacketTunnel(tunnel.Tunnel)
	defer func() { boundary.(*phonePacketTunnel).Close() }()
	source := &net.UDPAddr{IP: net.ParseIP("192.168.1.10"), Port: 54321}
	send := func(ip, payload string) {
		t.Helper()
		packet := &fixtureUDPPacket{data: []byte(payload), source: source, dropped: make(chan struct{})}
		boundary.HandleUDPPacket(packet, &C.Metadata{NetWork: C.UDP, Type: C.TUN, SrcIP: netip.MustParseAddr("192.168.1.10"), SrcPort: 54321, DstIP: netip.MustParseAddr(ip), DstPort: 32123})
		select {
		case <-packet.dropped:
		case <-time.After(3 * time.Second):
			t.Fatal("UDP packet was not processed")
		}
	}
	expect := func(want string) {
		t.Helper()
		select {
		case got := <-captured:
			if got != want {
				t.Fatalf("UDP route=%q, want %q", got, want)
			}
		case <-time.After(time.Second):
			t.Fatalf("missing actual captured UDP %q", want)
		}
	}
	absent := func() {
		t.Helper()
		select {
		case got := <-captured:
			t.Fatalf("forbidden UDP escaped via %q", got)
		case <-time.After(75 * time.Millisecond):
		}
	}
	// Same source socket: unsupported route must never reuse prior DIRECT NAT.
	send("8.8.8.8", "first")
	expect("direct:first")
	send("9.9.9.9", "blocked")
	absent()
	// Reverse transition: rejection must not poison the explicit DIRECT route.
	send("9.9.9.9", "blocked-again")
	absent()
	send("8.8.8.8", "second")
	expect("direct:second")
	// A supported proxy transport exercises both directions with distinct NAT
	// sessions and a new phone generation; no map entry is swapped mid-session.
	boundary.(*phonePacketTunnel).Close()
	retireTestCore(parsed)
	parsed, err = MC.ParseRawConfig(p.raw)
	if err != nil {
		t.Fatal(err)
	}
	for name, label := range map[string]string{"DIRECT": "direct", "A": "proxy"} {
		parsed.Proxies[name].(*adapter.Proxy).ProxyAdapter = &fixtureUDPAdapter{Direct: outbound.NewDirectWithOption(outbound.DirectOption{Name: name}), target: receiver.LocalAddr(), label: label}
	}
	if err := installUDPGuards(parsed); err != nil {
		t.Fatal(err)
	}
	executor.ApplyConfig(parsed, true)
	activateRuntime(parsed)
	boundary = newPhonePacketTunnel(tunnel.Tunnel)
	for _, step := range []struct{ ip, payload, route string }{{"8.8.8.8", "d1", "direct"}, {"9.9.9.9", "p1", "proxy"}, {"9.9.9.9", "p2", "proxy"}, {"8.8.8.8", "d2", "direct"}} {
		send(step.ip, step.payload)
		expect(fmt.Sprintf("%s:%s", step.route, step.payload))
	}
}

// This fixture also exercises the real Mihomo SOCKS5 UDP associate handshake and
// RFC1928 wire datagram, with a local controlled upstream and no public traffic.
func TestRealSOCKS5UDPWire(t *testing.T) {
	oldHook := dialer.DefaultSocketHook
	dialer.DefaultSocketHook = nil
	defer func() { dialer.DefaultSocketHook = oldHook }()
	tcp, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer tcp.Close()
	udp, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer udp.Close()
	handlerErr := make(chan error, 1)
	accepted := make(chan net.Conn, 1)
	go func() {
		conn, err := tcp.Accept()
		if err != nil {
			handlerErr <- err
			return
		}
		accepted <- conn
		defer conn.Close()
		var head [4]byte
		if _, err = io.ReadFull(conn, head[:2]); err != nil {
			handlerErr <- err
			return
		}
		if head[0] != 5 {
			handlerErr <- fmt.Errorf("not SOCKS5")
			return
		}
		methods := make([]byte, int(head[1]))
		if _, err = io.ReadFull(conn, methods); err != nil {
			handlerErr <- err
			return
		}
		conn.Write([]byte{5, 0})
		if _, err = io.ReadFull(conn, head[:]); err != nil {
			handlerErr <- err
			return
		}
		if head[0] != 5 || head[1] != 3 {
			handlerErr <- fmt.Errorf("expected UDP associate, got %v", head)
			return
		}
		size := 0
		switch head[3] {
		case 1:
			size = 4
		case 4:
			size = 16
		case 3:
			one := []byte{0}
			if _, err = io.ReadFull(conn, one); err != nil {
				handlerErr <- err
				return
			}
			size = int(one[0])
		default:
			handlerErr <- fmt.Errorf("bad SOCKS address")
			return
		}
		if _, err = io.ReadFull(conn, make([]byte, size+2)); err != nil {
			handlerErr <- err
			return
		}
		port := udp.LocalAddr().(*net.UDPAddr).Port
		reply := []byte{5, 0, 0, 1, 127, 0, 0, 1, byte(port >> 8), byte(port)}
		if _, err = conn.Write(reply); err != nil {
			handlerErr <- err
			return
		}
		handlerErr <- nil
		io.Copy(io.Discard, conn)
	}()
	defer func() {
		select {
		case c := <-accepted:
			c.Close()
		default:
		}
	}()
	cfg := testConfig()
	cfg.PhoneVPN = true
	body := []byte(`{"proxies":[{"name":"A","type":"socks5","server":"8.8.8.8","port":1080,"udp":true}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A"]}],"rules":["MATCH,Choice"]}`)
	p, err := sanitizeProfile(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	host, portText, _ := net.SplitHostPort(tcp.Addr().String())
	port, _ := strconv.Atoi(portText)
	p.raw.Proxy[0]["server"] = host
	p.raw.Proxy[0]["port"] = port
	parsed, err := MC.ParseRawConfig(p.raw)
	if err != nil {
		t.Fatal(err)
	}
	if err = installUDPGuards(parsed); err != nil {
		t.Fatal(err)
	}
	executor.ApplyConfig(parsed, true)
	activateRuntime(parsed)
	boundary := newPhonePacketTunnel(tunnel.Tunnel).(*phonePacketTunnel)
	defer func() {
		boundary.Close()
		retireTestCore(parsed)
	}()
	packet := &fixtureUDPPacket{data: []byte("actual-socks5-udp"), source: &net.UDPAddr{IP: net.ParseIP("192.168.1.10"), Port: 50001}, dropped: make(chan struct{})}
	boundary.HandleUDPPacket(packet, &C.Metadata{NetWork: C.UDP, Type: C.TUN, SrcIP: netip.MustParseAddr("192.168.1.10"), SrcPort: 50001, DstIP: netip.MustParseAddr("8.8.4.4"), DstPort: 32123})
	udp.SetReadDeadline(time.Now().Add(3 * time.Second))
	buf := make([]byte, 2048)
	n, _, err := udp.ReadFrom(buf)
	if err != nil {
		t.Fatal(err)
	}
	want := append([]byte{0, 0, 0, 1, 8, 8, 4, 4, byte(32123 >> 8), byte(32123 & 255)}, []byte("actual-socks5-udp")...)
	if !bytes.Equal(buf[:n], want) {
		t.Fatalf("SOCKS5 UDP wire=%v want %v", buf[:n], want)
	}
	if err := <-handlerErr; err != nil {
		t.Fatal(err)
	}
	select {
	case <-packet.dropped:
	case <-time.After(time.Second):
		t.Fatal("wire packet ownership not released")
	}
}

func retireTestCore(parsed *MC.Config) {
	e := &Engine{current: parsed}
	e.unloadLocked()
}
