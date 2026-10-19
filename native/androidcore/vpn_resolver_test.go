// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	D "github.com/miekg/dns"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func fixturePhoneResolver(server *httptest.Server) *phoneResolver {
	r := newPhoneResolver()
	r.endpoints = []string{server.URL + "/dns-query"}
	roots := x509.NewCertPool()
	roots.AddCert(server.Certificate())
	r.tlsConfig = &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12, NextProtos: []string{"http/1.1"}}
	// Only the test transport permits a loopback certificate endpoint. Production
	// keeps the fixed numeric public endpoints and socket protection Control.
	r.dial = (&net.Dialer{}).DialContext
	return r
}
func TestPhoneResolverVerifiedHTTPSWire(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		calls.Add(1)
		if req.ProtoMajor != 1 || !req.Close || req.Header.Get("Accept") != "application/dns-message" {
			t.Error("unexpected owned HTTP protocol")
		}
		payload, err := base64.RawURLEncoding.DecodeString(req.URL.Query().Get("dns"))
		if err != nil {
			t.Error(err)
			return
		}
		q := new(D.Msg)
		if q.Unpack(payload) != nil {
			t.Error("invalid DNS query")
			return
		}
		answer, _ := fixtureDNSResolver{}.ExchangeContext(req.Context(), q)
		wire, _ := answer.Pack()
		w.Header().Set("Content-Type", "application/dns-message")
		w.Write(wire)
	}))
	defer server.Close()
	r := fixturePhoneResolver(server)
	for _, qtype := range []uint16{D.TypeA, D.TypeAAAA} {
		q := new(D.Msg)
		q.SetQuestion("fixture.example.", qtype)
		answer, err := r.ExchangeContext(context.Background(), q)
		if err != nil || len(answer.Answer) != 1 {
			t.Fatalf("owned HTTPS DNS failed: %v", err)
		}
	}
	if calls.Load() != 2 {
		t.Fatal("unexpected DNS exchange count")
	}
	if err := r.Close(); err != nil {
		t.Fatal(err)
	}
	q := new(D.Msg)
	q.SetQuestion("fixture.example.", D.TypeA)
	if _, err := r.ExchangeContext(context.Background(), q); err == nil {
		t.Fatal("stopped resolver reopened connection")
	}
	if calls.Load() != 2 {
		t.Fatal("closed resolver sent more traffic")
	}
	// Without the fixture CA trust, the ordinary verifier rejects that endpoint.
	untrusted := newPhoneResolver()
	defer untrusted.Close()
	untrusted.endpoints = []string{server.URL}
	untrusted.dial = (&net.Dialer{}).DialContext
	if _, err := untrusted.ExchangeContext(context.Background(), q); err == nil {
		t.Fatal("untrusted TLS certificate accepted")
	}
}
func TestPhoneResolverCancellationJoinsBlockedTLS(t *testing.T) {
	r := newPhoneResolver()
	entered := make(chan struct{}, maxPhoneDNSQueries)
	cancelled := make(chan struct{}, maxPhoneDNSQueries)
	release := make(chan struct{})
	var calls atomic.Int32
	r.dial = func(ctx context.Context, _, _ string) (net.Conn, error) {
		calls.Add(1)
		entered <- struct{}{}
		<-ctx.Done()
		cancelled <- struct{}{}
		<-release
		return nil, ctx.Err()
	}
	q := new(D.Msg)
	q.SetQuestion("fixture.example.", D.TypeA)
	done := make(chan struct{}, maxPhoneDNSQueries)
	for i := 0; i < maxPhoneDNSQueries; i++ {
		go func() { r.ExchangeContext(context.Background(), q); done <- struct{}{} }()
	}
	for i := 0; i < maxPhoneDNSQueries; i++ {
		mustSignal(t, entered, "owned DNS dial missing")
	}
	if _, err := r.ExchangeContext(context.Background(), q); err == nil {
		t.Fatal("unbounded DNS dial admission")
	}
	stopped := make(chan struct{})
	go func() { r.Close(); close(stopped) }()
	for i := 0; i < maxPhoneDNSQueries; i++ {
		mustSignal(t, cancelled, "owned DNS dial not cancelled")
	}
	select {
	case <-stopped:
		t.Fatal("DNS close returned with pending dials")
	default:
	}
	close(release)
	mustSignal(t, stopped, "DNS close failed to join blocked dials")
	for i := 0; i < maxPhoneDNSQueries; i++ {
		mustSignal(t, done, "DNS exchange did not retire")
	}
	if calls.Load() != maxPhoneDNSQueries {
		t.Fatal("retry escaped cancelled DNS owner")
	}
}
func TestPhoneResolverCancellationClosesConnectedSocket(t *testing.T) {
	r := newPhoneResolver()
	local, peer := net.Pipe()
	defer peer.Close()
	r.dial = func(context.Context, string, string) (net.Conn, error) { return local, nil }
	q := new(D.Msg)
	q.SetQuestion("fixture.example.", D.TypeA)
	done := make(chan struct{})
	go func() { r.ExchangeContext(context.Background(), q); close(done) }()
	// The TLS ClientHello proves the query owns a connected socket and is blocked
	// waiting for a handshake reply. No real network or public DNS is contacted.
	peer.SetReadDeadline(time.Now().Add(time.Second))
	header := make([]byte, 5)
	if _, err := io.ReadFull(peer, header); err != nil {
		t.Fatal(err)
	}
	if err := r.Close(); err != nil {
		t.Fatal(err)
	}
	mustSignal(t, done, "connected DNS socket survived cancellation")
	peer.SetReadDeadline(time.Now().Add(time.Second))
	if _, err := peer.Read(make([]byte, 1)); err == nil {
		t.Fatal("DNS connection remained open")
	}
}

func TestPhoneResolverRejectsMalformedHTTPS(t *testing.T) {
	for _, kind := range []string{"oversized-header", "oversized-body", "wrong-id", "wrong-question", "redirect"} {
		t.Run(kind, func(t *testing.T) {
			server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				if kind == "redirect" {
					w.Header().Set("Location", "https://1.1.1.1/elsewhere")
					w.WriteHeader(http.StatusFound)
					return
				}
				if kind == "oversized-header" {
					w.Header().Set("X-Oversized", strings.Repeat("x", 90*1024))
				}
				w.Header().Set("Content-Type", "application/dns-message")
				if kind == "oversized-body" {
					w.Write(make([]byte, 65536))
					return
				}
				wire, _ := base64.RawURLEncoding.DecodeString(req.URL.Query().Get("dns"))
				q := new(D.Msg)
				q.Unpack(wire)
				answer, _ := fixtureDNSResolver{}.ExchangeContext(req.Context(), q)
				if kind == "wrong-id" {
					answer.Id++
				}
				if kind == "wrong-question" {
					answer.Question[0].Name = "other.example."
				}
				wire, _ = answer.Pack()
				w.Write(wire)
			}))
			defer server.Close()
			r := fixturePhoneResolver(server)
			defer r.Close()
			q := new(D.Msg)
			q.SetQuestion("fixture.example.", D.TypeA)
			if _, err := r.ExchangeContext(context.Background(), q); err == nil {
				t.Fatalf("accepted %s", kind)
			}
		})
	}
}
func TestPhoneResolverProtectionFailsClosed(t *testing.T) {
	owner := &Engine{}
	protect := &fixtureProtector{allowed: false}
	requirePhoneSocketProtection(owner, protect)
	defer ReleasePhoneVPNProtection()
	if phoneDNSControl("tcp", "1.1.1.1:443", fixtureRawConn{}) == nil || protect.calls != 1 {
		t.Fatal("DNS ignored protect=false")
	}
	protect.allowed = true
	if err := phoneDNSControl("tcp", "1.1.1.1:443", fixtureRawConn{}); err != nil {
		t.Fatal(err)
	}
	if phoneDNSControl("tcp", "127.0.0.1:443", fixtureRawConn{}) == nil {
		t.Fatal("DNS Control permitted private endpoint")
	}
}
