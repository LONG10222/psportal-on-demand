// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"net"
	"net/netip"
	"sync/atomic"
	"testing"
	"time"

	"github.com/metacubex/mihomo/component/resolver"
	"github.com/metacubex/sing/common/buf"
	M "github.com/metacubex/sing/common/metadata"
	N "github.com/metacubex/sing/common/network"
	D "github.com/miekg/dns"
)

type blockedPhoneDNS struct {
	entered   chan struct{}
	cancelled chan struct{}
	release   chan struct{}
	calls     atomic.Int32
}

func (s *blockedPhoneDNS) ServeMsg(ctx context.Context, q *D.Msg) (*D.Msg, error) {
	s.calls.Add(1)
	s.entered <- struct{}{}
	<-ctx.Done()
	s.cancelled <- struct{}{}
	<-s.release
	return nil, ctx.Err()
}

type phoneDNSWriter struct{ written chan []byte }

func (w phoneDNSWriter) WritePacket(p *buf.Buffer, _ M.Socksaddr) error {
	defer p.Release()
	w.written <- append([]byte(nil), p.Bytes()...)
	return nil
}
func phoneDNSQuery() []byte {
	q := new(D.Msg)
	q.SetQuestion("fixture.example.", D.TypeA)
	b, _ := q.Pack()
	return b
}
func sendPhoneDNS(h *phoneDNSHandler, w phoneDNSWriter) {
	p := buf.NewSize(256)
	p.Write(phoneDNSQuery())
	h.NewPacket(context.Background(), netip.MustParseAddrPort("198.18.0.1:53000"), p, M.Metadata{Destination: M.ParseSocksaddr("198.18.0.2:53")}, func(N.PacketConn) N.PacketWriter { return w })
}
func mustSignal(t *testing.T, ch <-chan struct{}, message string) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(3 * time.Second):
		t.Fatal(message)
	}
}

func TestPhoneDNSBoundedCancelJoinAndSnapshot(t *testing.T) {
	service := &blockedPhoneDNS{entered: make(chan struct{}, maxPhoneDNSQueries), cancelled: make(chan struct{}, maxPhoneDNSQueries), release: make(chan struct{})}
	h, err := newPhoneDNSHandler(nil, service)
	if err != nil {
		t.Fatal(err)
	}
	writer := phoneDNSWriter{written: make(chan []byte, 1)}
	for i := 0; i < maxPhoneDNSQueries+20; i++ {
		sendPhoneDNS(h, writer)
	}
	for i := 0; i < maxPhoneDNSQueries; i++ {
		mustSignal(t, service.entered, "owned DNS query did not start")
	}
	if service.calls.Load() != maxPhoneDNSQueries {
		t.Fatal("DNS query cap not enforced")
	}
	closed := make(chan struct{})
	go func() { h.Close(); close(closed) }()
	for i := 0; i < maxPhoneDNSQueries; i++ {
		mustSignal(t, service.cancelled, "DNS query not cancelled")
	}
	select {
	case <-closed:
		t.Fatal("Close returned before query exit")
	default:
	}
	close(service.release)
	mustSignal(t, closed, "Close did not join DNS queries")
	sendPhoneDNS(h, writer)
	if service.calls.Load() != maxPhoneDNSQueries {
		t.Fatal("closed DNS handler admitted query")
	}
	select {
	case <-writer.written:
		t.Fatal("cancelled DNS replied after stop")
	default:
	}
	old := resolver.DefaultService
	resolver.DefaultService = service
	defer func() { resolver.DefaultService = old }()
	next, err := newPhoneDNSHandler(nil, fixtureDNSService{})
	if err != nil {
		t.Fatal(err)
	}
	defer next.Close()
	sendPhoneDNS(next, writer)
	select {
	case wire := <-writer.written:
		msg := new(D.Msg)
		if msg.Unpack(wire) != nil || len(msg.Answer) != 1 {
			t.Fatal("next DNS session failed")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("next DNS session used stale service")
	}
	if service.calls.Load() != maxPhoneDNSQueries {
		t.Fatal("new handler consulted global service")
	}
}

type fixtureDNSService struct{}

func (fixtureDNSService) ServeMsg(ctx context.Context, q *D.Msg) (*D.Msg, error) {
	return fixtureDNSResolver{}.ExchangeContext(ctx, q)
}
func TestPhoneDNSStopClosesIdleTCP(t *testing.T) {
	h, err := newPhoneDNSHandler(nil, fixtureDNSService{})
	if err != nil {
		t.Fatal(err)
	}
	client, server := net.Pipe()
	defer client.Close()
	done := make(chan struct{})
	go func() {
		h.NewConnection(context.Background(), server, M.Metadata{Destination: M.ParseSocksaddr("198.18.0.2:53")})
		close(done)
	}()
	deadline := time.Now().Add(time.Second)
	for {
		h.mu.Lock()
		active := h.active
		h.mu.Unlock()
		if active == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("TCP DNS not admitted")
		}
		time.Sleep(time.Millisecond)
	}
	if err = h.Close(); err != nil {
		t.Fatal(err)
	}
	mustSignal(t, done, "idle TCP DNS did not retire")
}
