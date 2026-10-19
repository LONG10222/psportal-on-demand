// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/base64"
	"errors"
	"io"
	"mime"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"sync"
	"syscall"

	"github.com/metacubex/mihomo/component/resolver"
	C "github.com/metacubex/mihomo/constant"
	MDNS "github.com/metacubex/mihomo/dns"
	D "github.com/miekg/dns"
)

// No detached refresh, singleflight worker, connection pool or background dial
// is used. One admitted operation owns its TCP/TLS connection until completion.
// The fixed numeric HTTPS endpoints require no plaintext/system DNS bootstrap.
type phoneResolver struct {
	ctx       context.Context
	cancel    context.CancelFunc
	mu        sync.Mutex
	closed    bool
	active    int
	wg        sync.WaitGroup
	closeDone chan struct{}
	endpoints []string
	dial      func(context.Context, string, string) (net.Conn, error)
	tlsConfig *tls.Config
}

func newPhoneResolver() *phoneResolver {
	ctx, cancel := context.WithCancel(context.Background())
	d := &net.Dialer{Control: phoneDNSControl}
	return &phoneResolver{ctx: ctx, cancel: cancel, closeDone: make(chan struct{}), endpoints: []string{"https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"}, dial: d.DialContext, tlsConfig: &tls.Config{MinVersion: tls.VersionTLS12, NextProtos: []string{"http/1.1"}}}
}
func phoneDNSControl(network, address string, raw syscall.RawConn) error {
	if err := guardSocketDestination(network, address); err != nil {
		return err
	}
	return protectVPNRawConn(raw)
}

func (r *phoneResolver) begin(parent context.Context) (context.Context, func(), error) {
	r.mu.Lock()
	if r.closed || r.active >= maxPhoneDNSQueries {
		r.mu.Unlock()
		return nil, nil, errors.New("phone DNS is stopped or busy")
	}
	r.active++
	r.wg.Add(1)
	r.mu.Unlock()
	ctx, cancel := context.WithTimeout(parent, resolver.DefaultDNSTimeout)
	stop := context.AfterFunc(r.ctx, cancel)
	return ctx, func() {
		stop()
		cancel()
		r.mu.Lock()
		r.active--
		r.mu.Unlock()
		r.wg.Done()
	}, nil
}
func (r *phoneResolver) ExchangeContext(parent context.Context, q *D.Msg) (*D.Msg, error) {
	if q == nil || len(q.Question) != 1 {
		return nil, errors.New("DNS requires one question")
	}
	wire, err := q.Pack()
	if err != nil || len(wire) > maxPhoneDNSMessage {
		return nil, errors.New("invalid DNS message")
	}
	ctx, done, err := r.begin(parent)
	if err != nil {
		return nil, err
	}
	defer done()
	var last error
	for _, endpoint := range r.endpoints {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		answer, err := r.exchange(ctx, endpoint, wire, q)
		if err == nil {
			return answer, nil
		}
		last = err
	}
	return nil, last
}
func (r *phoneResolver) exchange(ctx context.Context, endpoint string, wire []byte, q *D.Msg) (*D.Msg, error) {
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme != "https" || u.User != nil {
		return nil, errors.New("invalid owned DNS endpoint")
	}
	if _, err = netip.ParseAddr(u.Hostname()); err != nil {
		return nil, errors.New("DNS endpoint must be numeric")
	}
	port := u.Port()
	if port == "" {
		port = "443"
	}
	raw, err := r.dial(ctx, "tcp", net.JoinHostPort(u.Hostname(), port))
	if err != nil {
		return nil, err
	}
	// Joining the close callback prevents old query cleanup leaking into restart.
	closed := make(chan struct{})
	stop := context.AfterFunc(ctx, func() { _ = raw.Close(); close(closed) })
	defer func() {
		if !stop() {
			<-closed
		}
		_ = raw.Close()
	}()
	if deadline, ok := ctx.Deadline(); ok {
		_ = raw.SetDeadline(deadline)
	}
	config := r.tlsConfig.Clone()
	config.ServerName = u.Hostname()
	conn := tls.Client(raw, config)
	if err = conn.HandshakeContext(ctx); err != nil {
		return nil, err
	}
	u.RawQuery = "dns=" + base64.RawURLEncoding.EncodeToString(wire)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, err
	}
	req.Close = true
	req.Header.Set("Accept", "application/dns-message")
	if err = req.Write(conn); err != nil {
		return nil, err
	}
	// Bound the entire wire response, including headers, chunk framing and trailers.
	response, err := http.ReadResponse(bufio.NewReader(io.LimitReader(conn, 80*1024)), req)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, errors.New("DNS HTTPS endpoint did not return HTTP 200")
	}
	contentType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil || contentType != "application/dns-message" {
		return nil, errors.New("invalid DNS HTTPS content type")
	}
	payload, err := io.ReadAll(io.LimitReader(response.Body, 65536))
	if err != nil || len(payload) > 65535 {
		return nil, errors.New("DNS HTTPS response exceeds limit")
	}
	answer := new(D.Msg)
	if err = answer.Unpack(payload); err != nil {
		return nil, err
	}
	if !answer.Response || answer.Id != q.Id || len(answer.Question) != 1 || answer.Question[0] != q.Question[0] {
		return nil, errors.New("DNS HTTPS response does not match query")
	}
	if answer.Rcode == D.RcodeServerFailure || answer.Rcode == D.RcodeRefused {
		return nil, errors.New("DNS HTTPS resolver rejected query")
	}
	return answer, nil
}
func (r *phoneResolver) lookup(ctx context.Context, host string, qtype uint16) ([]netip.Addr, error) {
	if ip, err := netip.ParseAddr(host); err == nil {
		ip = ip.Unmap()
		if (qtype == D.TypeA && ip.Is4()) || (qtype == D.TypeAAAA && ip.Is6()) {
			return []netip.Addr{ip}, nil
		}
		return nil, resolver.ErrIPVersion
	}
	query := new(D.Msg)
	query.SetQuestion(D.Fqdn(host), qtype)
	answer, err := r.ExchangeContext(ctx, query)
	if err != nil {
		return nil, err
	}
	var addresses []netip.Addr
	for _, record := range answer.Answer {
		switch record := record.(type) {
		case *D.A:
			if qtype == D.TypeA {
				if ip, ok := netip.AddrFromSlice(record.A); ok {
					addresses = append(addresses, ip.Unmap())
				}
			}
		case *D.AAAA:
			if qtype == D.TypeAAAA {
				if ip, ok := netip.AddrFromSlice(record.AAAA); ok {
					addresses = append(addresses, ip)
				}
			}
		}
	}
	if len(addresses) == 0 {
		return nil, resolver.ErrIPNotFound
	}
	return addresses, nil
}
func (r *phoneResolver) LookupIPv4(ctx context.Context, host string) ([]netip.Addr, error) {
	return r.lookup(ctx, host, D.TypeA)
}
func (r *phoneResolver) LookupIPv6(ctx context.Context, host string) ([]netip.Addr, error) {
	return r.lookup(ctx, host, D.TypeAAAA)
}
func (r *phoneResolver) LookupIP(ctx context.Context, host string) ([]netip.Addr, error) {
	v4, e4 := r.LookupIPv4(ctx, host)
	v6, e6 := r.LookupIPv6(ctx, host)
	if len(v4)+len(v6) == 0 {
		return nil, errors.Join(e4, e6)
	}
	return append(v4, v6...), nil
}
func (r *phoneResolver) ResolveECH(ctx context.Context, host string) ([]byte, error) {
	q := new(D.Msg)
	q.SetQuestion(D.Fqdn(host), D.TypeHTTPS)
	answer, err := r.ExchangeContext(ctx, q)
	if err != nil {
		return nil, err
	}
	for _, record := range answer.Answer {
		if https, ok := record.(*D.HTTPS); ok {
			for _, value := range https.Value {
				if ech, ok := value.(*D.SVCBECHConfig); ok {
					return append([]byte(nil), ech.ECH...), nil
				}
			}
		}
	}
	return nil, errors.New("no ECH DNS record")
}
func (*phoneResolver) Invalid() bool    { return true } // true means usable in upstream's interface
func (*phoneResolver) ClearCache()      {}
func (*phoneResolver) ResetConnection() {} // no pooled connections; Close owns terminal teardown
func (r *phoneResolver) Close() error {
	r.mu.Lock()
	if r.closed {
		r.mu.Unlock()
		<-r.closeDone
		return nil
	}
	r.closed = true
	r.cancel()
	r.mu.Unlock()
	r.wg.Wait()
	close(r.closeDone)
	return nil
}

var _ resolver.Resolver = (*phoneResolver)(nil)

func installOwnedPhoneDNS() {
	// ApplyConfig's resolvers have not been activated for endpoint/provider work.
	for _, old := range []resolver.Resolver{resolver.DefaultResolver, resolver.ProxyServerHostResolver, resolver.DirectHostResolver} {
		if old != nil {
			old.ResetConnection()
		}
	}
	owned := newPhoneResolver()
	mapper := MDNS.NewEnhancer(MDNS.EnhancerConfig{IPv6: true, EnhancedMode: C.DNSMapping})
	resolver.DefaultResolver = owned
	resolver.ProxyServerHostResolver = filteredResolver{owned}
	resolver.DirectHostResolver = filteredResolver{owned}
	resolver.DefaultHostMapper = mapper
	resolver.DefaultService = MDNS.NewService(owned, mapper)
}
func closeOwnedPhoneDNS() {
	if owned, ok := resolver.DefaultResolver.(*phoneResolver); ok {
		_ = owned.Close()
	}
}
