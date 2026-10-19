// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	N "github.com/metacubex/mihomo/common/net"
	"github.com/metacubex/mihomo/component/dialer"
	"github.com/metacubex/mihomo/component/resolver"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
	MDNS "github.com/metacubex/mihomo/dns"
	"github.com/metacubex/mihomo/hub/executor"
	"github.com/metacubex/mihomo/tunnel"
	D "github.com/miekg/dns"
)

type fixtureRawConn struct{ fail bool }

func (r fixtureRawConn) Control(fn func(uintptr)) error {
	if r.fail {
		return errors.New("fixture")
	}
	fn(42)
	return nil
}
func (fixtureRawConn) Read(func(uintptr) bool) error  { return nil }
func (fixtureRawConn) Write(func(uintptr) bool) error { return nil }

var _ syscall.RawConn = fixtureRawConn{}

type fixtureProtector struct {
	allowed bool
	calls   int
}

func (p *fixtureProtector) Protect(fd int) bool {
	if fd != 42 {
		panic("unexpected fd")
	}
	p.calls++
	return p.allowed
}

func TestPhoneSocketProtectionFailClosed(t *testing.T) {
	defer ReleasePhoneVPNProtection()
	p := &fixtureProtector{}
	vpnProtection.Lock()
	vpnProtection.required = true
	vpnProtection.protector = p
	vpnProtection.Unlock()
	if protectVPNRawConn(fixtureRawConn{}) == nil || p.calls != 1 {
		t.Fatal("protect=false allowed a socket")
	}
	p.allowed = true
	if err := protectVPNRawConn(fixtureRawConn{}); err != nil {
		t.Fatal(err)
	}
	if protectVPNRawConn(fixtureRawConn{fail: true}) == nil || p.calls != 2 {
		t.Fatal("raw control failure was ignored")
	}
	vpnProtection.Lock()
	vpnProtection.protector = nil
	vpnProtection.Unlock()
	if protectVPNRawConn(fixtureRawConn{}) == nil {
		t.Fatal("teardown opened an unprotected socket")
	}
	ReleasePhoneVPNProtection()
	if err := protectVPNRawConn(fixtureRawConn{}); err != nil {
		t.Fatal("LAN-only socket policy did not resume")
	}
}

type keyCaptureTunnel struct {
	C.Tunnel
	packets  []C.UDPPacket
	metadata []*C.Metadata
}

func (t *keyCaptureTunnel) HandleUDPPacket(p C.UDPPacket, m *C.Metadata) {
	t.packets = append(t.packets, p)
	t.metadata = append(t.metadata, m)
}

func (t *keyCaptureTunnel) drain() {
	for _, p := range t.packets {
		p.Drop()
	}
}

type keyFixturePacket struct {
	data             []byte
	dropped, replies int
}

func (p *keyFixturePacket) Data() []byte { return p.data }
func (p *keyFixturePacket) Drop()        { p.dropped++ }
func (p *keyFixturePacket) LocalAddr() net.Addr {
	return &net.UDPAddr{IP: net.ParseIP("198.18.0.1"), Port: 42000}
}
func (p *keyFixturePacket) WriteBack(data []byte, _ net.Addr) (int, error) {
	p.replies++
	return len(data), nil
}

func TestPhonePacketDestinationIsolation(t *testing.T) {
	capture := &keyCaptureTunnel{}
	first := newPhonePacketTunnel(capture)
	defer first.(*phonePacketTunnel).Close()
	packet := &keyFixturePacket{data: []byte("fixture payload")}
	meta := func(ip string, port uint16, host string) *C.Metadata {
		return &C.Metadata{NetWork: C.UDP, Type: C.TUN, DstIP: netip.MustParseAddr(ip), DstPort: port, Host: host}
	}
	for _, m := range []*C.Metadata{meta("8.8.8.8", 443, ""), meta("8.8.8.8", 443, ""), meta("1.1.1.1", 443, ""), meta("8.8.8.8", 53, ""), meta("2001:4860:4860::8888", 443, ""), meta("8.8.8.8", 443, "other.example")} {
		first.HandleUDPPacket(packet, m)
	}
	second := newPhonePacketTunnel(capture)
	defer second.(*phonePacketTunnel).Close()
	defer capture.drain()
	second.HandleUDPPacket(packet, meta("8.8.8.8", 443, ""))
	if len(capture.packets) != 7 {
		t.Fatal("public packets not forwarded")
	}
	key := func(i int) string { return capture.packets[i].LocalAddr().String() }
	if key(0) != key(1) {
		t.Fatal("same flow lost NAT association")
	}
	seen := map[string]bool{key(0): true}
	for i := 2; i < 7; i++ {
		if seen[key(i)] {
			t.Fatal("destination/host/session shared NAT key")
		}
		seen[key(i)] = true
	}
	if string(capture.packets[0].Data()) != "fixture payload" {
		t.Fatal("payload changed")
	}
	if n, err := capture.packets[0].WriteBack([]byte("reply"), nil); err != nil || n != 5 || packet.replies != 1 {
		t.Fatal("reply path lost")
	}
	capture.packets[0].Drop()
	if packet.dropped != 1 {
		t.Fatal("buffer drop not delegated")
	}
	for _, ip := range []string{"127.0.0.1", "192.168.1.1", "169.254.169.254", "::1", "fd00::1", "fe80::1"} {
		first.HandleUDPPacket(packet, meta(ip, 80, ""))
	}
	first.HandleUDPPacket(packet, &C.Metadata{Host: "unresolved.example", DstPort: 443})
	if len(capture.packets) != 7 || packet.dropped != 8 {
		t.Fatal("private/unresolved UDP escaped packet boundary")
	}
}

type fixtureDNSResolver struct{ resolver.Resolver }

func (fixtureDNSResolver) ExchangeContext(_ context.Context, q *D.Msg) (*D.Msg, error) {
	r := new(D.Msg)
	r.SetReply(q)
	if q.Question[0].Qtype == D.TypeAAAA {
		r.Answer = []D.RR{&D.AAAA{Hdr: D.RR_Header{Name: q.Question[0].Name, Rrtype: D.TypeAAAA, Class: D.ClassINET, Ttl: 60}, AAAA: net.ParseIP("2001:4860:4860::8844")}}
	} else {
		r.Answer = []D.RR{&D.A{Hdr: D.RR_Header{Name: q.Question[0].Name, Rrtype: D.TypeA, Class: D.ClassINET, Ttl: 60}, A: net.ParseIP("8.8.4.4")}}
	}
	return r, nil
}

// Real wire DNS decoding/relay, Mihomo mapping, TUN metadata and DOMAIN matcher.
// The HTTP proxy endpoint is loopback test-only; no host TUN or public I/O occurs.
func TestPhoneDNSMappingRoutesDomain(t *testing.T) {
	oldHook := dialer.DefaultSocketHook
	dialer.DefaultSocketHook = nil
	defer func() { dialer.DefaultSocketHook = oldHook }()
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, rw, err := w.(http.Hijacker).Hijack()
		if err != nil {
			return
		}
		defer conn.Close()
		fmt.Fprint(rw, "HTTP/1.1 200 Connection Established\r\n\r\n")
		rw.Flush()
		request, err := http.ReadRequest(rw.Reader)
		if err != nil {
			return
		}
		request.Body.Close()
		fmt.Fprint(rw, "HTTP/1.1 200 OK\r\nContent-Length: 13\r\nConnection: close\r\n\r\ndomain-routed")
		rw.Flush()
	}))
	defer proxy.Close()
	cfg := testConfig()
	cfg.PhoneVPN = true
	body := strings.TrimSuffix(string(testBody()), "}") + `,"rules":["DOMAIN,phone-fixture.example,A","MATCH,REJECT"]}`
	p, err := sanitizeProfile([]byte(body), cfg)
	if err != nil {
		t.Fatal(err)
	}
	if p.raw.DNS.EnhancedMode != C.DNSMapping || p.raw.DNS.Listen != "" || !p.raw.DNS.IPv6 {
		t.Fatal("owned dual-stack DNS mapping is absent")
	}
	host, port, _ := net.SplitHostPort(strings.TrimPrefix(proxy.URL, "http://"))
	pn, _ := strconv.Atoi(port)
	p.raw.Proxy[0]["server"], p.raw.Proxy[0]["port"] = host, pn
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
	e.profile = p
	defer func() { e.cancel(); e.mu.Lock(); e.unloadLocked(); e.mu.Unlock() }()
	mapper := MDNS.NewEnhancer(MDNS.EnhancerConfig{IPv6: true, EnhancedMode: C.DNSMapping})
	resolver.DefaultHostMapper = mapper
	resolver.DefaultService = MDNS.NewService(fixtureDNSResolver{}, mapper)
	dnsHandler, err := newPhoneDNSHandler(nil, resolver.DefaultService)
	if err != nil {
		t.Fatal(err)
	}
	defer dnsHandler.Close()
	for _, qtype := range []uint16{D.TypeA, D.TypeAAAA} {
		q := new(D.Msg)
		q.SetQuestion("phone-fixture.example.", qtype)
		wire, _ := q.Pack()
		answer, err := dnsHandler.answer(wire, true)
		if err != nil {
			t.Fatal(err)
		}
		decoded := new(D.Msg)
		if decoded.Unpack(answer) != nil || len(decoded.Answer) != 1 {
			t.Fatal("DNS packet was not answered")
		}
		ip := netip.MustParseAddr("8.8.4.4")
		if qtype == D.TypeAAAA {
			ip = netip.MustParseAddr("2001:4860:4860::8844")
		}
		if host, ok := mapper.FindHostByIP(ip); !ok || host != "phone-fixture.example" {
			t.Fatal("DNS answer missing domain mapping")
		}
		client, server := N.Pipe()
		metadata := &C.Metadata{NetWork: C.TCP, Type: C.TUN, DstIP: ip, DstPort: 80}
		done := make(chan struct{})
		go func() {
			owner := newPhonePacketTunnel(tunnel.Tunnel).(*phonePacketTunnel)
			owner.HandleTCPConn(server, metadata)
			owner.Close()
			close(done)
		}()
		client.SetDeadline(time.Now().Add(3 * time.Second))
		fmt.Fprint(client, "GET / HTTP/1.1\r\nHost: phone-fixture.example\r\nConnection: close\r\n\r\n")
		res, err := http.ReadResponse(bufio.NewReader(client), nil)
		if err != nil {
			client.Close()
			t.Fatal(err)
		}
		got, _ := io.ReadAll(res.Body)
		res.Body.Close()
		client.Close()
		<-done
		if string(got) != "domain-routed" {
			t.Fatalf("DOMAIN route failed: %q", got)
		}
	}
}

// The budget counts pending dials as well as established sockets. No timers
// silently discard ownership of a socket that is still open.
func TestPhoneUDPFlowBudgetAndCleanup(t *testing.T) {
	capture := &keyCaptureTunnel{}
	owner := newPhonePacketTunnel(capture).(*phonePacketTunnel)
	defer owner.Close()
	packet := &keyFixturePacket{}
	send := func(port uint16) {
		owner.HandleUDPPacket(packet, &C.Metadata{NetWork: C.UDP, Type: C.TUN, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: port})
	}
	for i := 0; i < maxPhoneUDPFlows; i++ {
		send(uint16(1000 + i))
	}
	send(5000)
	if len(capture.packets) != maxPhoneUDPFlows || packet.dropped != 1 {
		t.Fatal("pending UDP flow budget not enforced")
	}
	first := capture.metadata[0]
	if _, err := trackPhoneUDPResult(first, nil, errors.New("fixture failure")); err == nil {
		t.Fatal("terminal failure missing")
	}
	send(1000)
	if len(capture.packets) != maxPhoneUDPFlows+1 || capture.metadata[len(capture.metadata)-1].InName == first.InName {
		t.Fatal("released flow reused stale NAT nonce")
	}
	pc := &fixtureOwnedUDP{}
	wrapped, err := trackPhoneUDPResult(capture.metadata[1], pc, nil)
	if err != nil {
		t.Fatal(err)
	}
	again, err := trackPhoneUDPResult(capture.metadata[1], wrapped, nil)
	if err != nil || again != wrapped {
		t.Fatal("nested group double ownership")
	}
	capture.drain()
	if err = owner.Close(); err != nil {
		t.Fatal(err)
	}
	if pc.closed != 1 {
		t.Fatal("owned UDP socket not closed exactly once")
	}
	_ = wrapped.Close()
	if pc.closed != 1 {
		t.Fatal("second close reached underlying socket")
	}
	for _, m := range capture.metadata {
		if flow, _ := phoneFlowFor(m); flow != nil {
			t.Fatal("phone flow survived close")
		}
	}
	before := packet.dropped
	send(1000)
	if packet.dropped != before+1 {
		t.Fatal("closed tunnel accepted a packet")
	}
}

type fixtureOwnedUDP struct {
	C.PacketConn
	closed int
}

func (p *fixtureOwnedUDP) Close() error { p.closed++; return nil }

func TestPhoneUDPStopCancelsPendingAndClosesLateResult(t *testing.T) {
	capture := &keyCaptureTunnel{}
	owner := newPhonePacketTunnel(capture).(*phonePacketTunnel)
	owner.HandleUDPPacket(&keyFixturePacket{}, &C.Metadata{NetWork: C.UDP, Type: C.TUN, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: 443})
	metadata := capture.metadata[0]
	ctx, done, err := phoneUDPContext(context.Background(), metadata)
	if err != nil {
		t.Fatal(err)
	}
	stopped := make(chan struct{})
	go func() { owner.Close(); close(stopped) }()
	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("pending protocol setup not cancelled")
	}
	select {
	case <-stopped:
		t.Fatal("stop returned before pending dial retired")
	default:
	}
	late := &fixtureOwnedUDP{}
	if _, err = trackPhoneUDPResult(metadata, late, nil); err == nil || late.closed != 1 {
		t.Fatal("late socket was retained after stop")
	}
	done()
	done()
	capture.drain()
	select {
	case <-stopped:
	case <-time.After(time.Second):
		t.Fatal("dial completion did not release stop")
	}
	if _, _, err = phoneUDPContext(context.Background(), metadata); err == nil {
		t.Fatal("stale token allowed a new dial")
	}
}

func TestPhoneFailureProtectionReleasedBeforeLANRestart(t *testing.T) {
	for _, stage := range []string{"stack creation", "stack start"} {
		t.Run(stage, func(t *testing.T) {
			owner := &Engine{}
			p := &fixtureProtector{allowed: true}
			requirePhoneSocketProtection(owner, p)
			blockPhoneSocketProtection(owner) // same deferred failure path as Android bridge
			if protectVPNRawConn(fixtureRawConn{}) == nil {
				t.Fatal("failed stack allowed an unprotected socket before fd close")
			}
			ReleasePhoneVPNProtection() // Java calls only after closing its original fd
			if err := protectVPNRawConn(fixtureRawConn{}); err != nil {
				t.Fatal("failure stranded next LAN-only session")
			}
			next := &Engine{}
			requirePhoneSocketProtection(next, p)
			blockPhoneSocketProtection(owner) // stale cleanup must not clear the next owner
			if err := protectVPNRawConn(fixtureRawConn{}); err != nil {
				t.Fatal("old cleanup invalidated new owner")
			}
			ReleasePhoneVPNProtection()
		})
	}
}

func TestPhoneQueueRejectionReleasesPendingBudget(t *testing.T) {
	capture := &keyCaptureTunnel{}
	owner := newPhonePacketTunnel(capture).(*phonePacketTunnel)
	defer owner.Close()
	defer capture.drain()
	source := &keyFixturePacket{}
	metadata := &C.Metadata{NetWork: C.UDP, Type: C.TUN, DstIP: netip.MustParseAddr("8.8.8.8"), DstPort: 443}
	owner.HandleUDPPacket(source, metadata)
	token := capture.metadata[0].InName
	capture.packets[0].Drop() // e.g. upstream bounded packet queue rejected it
	if flow, _ := phoneFlowFor(capture.metadata[0]); flow != nil {
		t.Fatal("rejected queue entry retained budget")
	}
	owner.HandleUDPPacket(source, metadata)
	if capture.metadata[1].InName == token {
		t.Fatal("retry reused a rejected flow nonce")
	}
}

func TestPhoneSocketPolicyOwnershipRetires(t *testing.T) {
	initializeSocketPolicy()
	socketPolicy.Lock()
	oldPrevious, oldOwner := socketPolicy.previous, socketPolicy.owner
	var calls atomic.Int32
	socketPolicy.previous = func(string, string, syscall.RawConn) error { calls.Add(1); return nil }
	socketPolicy.owner = nil
	socketPolicy.Unlock()
	defer func() {
		socketPolicy.Lock()
		socketPolicy.previous, socketPolicy.owner = oldPrevious, oldOwner
		socketPolicy.Unlock()
	}()
	if err := dialer.DefaultSocketHook("tcp", "127.0.0.1:80", fixtureRawConn{}); err != nil || calls.Load() != 1 {
		t.Fatal("inactive dispatcher failed to delegate previous hook")
	}
	owner := &Engine{}
	activateSocketPolicy(owner)
	if dialer.DefaultSocketHook("tcp", "127.0.0.1:80", fixtureRawConn{}) == nil {
		t.Fatal("active owner omitted destination guard")
	}
	retireSocketPolicy(&Engine{})
	if dialer.DefaultSocketHook("tcp", "127.0.0.1:80", fixtureRawConn{}) == nil {
		t.Fatal("stale owner retired active policy")
	}
	retireSocketPolicy(owner)
	if err := dialer.DefaultSocketHook("tcp", "127.0.0.1:80", fixtureRawConn{}); err != nil || calls.Load() != 2 {
		t.Fatal("retired dispatcher retained destination restrictions")
	}
}
