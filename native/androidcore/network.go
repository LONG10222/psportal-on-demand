// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"errors"
	"github.com/metacubex/mihomo/component/resolver"
	"github.com/miekg/dns"
	"github.com/psportal/psportal/native/engine"
	"io"
	"net"
	"net/http"
	"net/netip"
	"time"
)

func publicAddresses(ctx context.Context, host string) ([]netip.Addr, error) {
	if ip, err := netip.ParseAddr(host); err == nil {
		if engine.Destination(ip.String()) != "external" {
			return nil, engine.ErrDestinationDenied
		}
		return []netip.Addr{ip}, nil
	}
	if engine.Destination(host) != "name" {
		return nil, engine.ErrDestinationDenied
	}
	ips, err := net.DefaultResolver.LookupNetIP(ctx, "ip", host)
	if err != nil || len(ips) == 0 {
		return nil, engine.ErrResolutionFailed
	}
	for _, ip := range ips {
		if engine.Destination(ip.Unmap().String()) != "external" {
			return nil, engine.ErrDestinationDenied
		}
	}
	return ips, nil
}
func publicDial(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, engine.ErrDestinationDenied
	}
	ips, err := publicAddresses(ctx, host)
	if err != nil {
		return nil, err
	}
	var result error
	for _, ip := range ips {
		conn, e := (&net.Dialer{}).DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
		if e == nil {
			return conn, nil
		}
		result = e
	}
	return nil, result
}
func download(ctx context.Context, url string) ([]byte, error) {
	tr := &http.Transport{Proxy: nil, DialContext: publicDial, TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 15 * time.Second, DisableKeepAlives: true}
	defer tr.CloseIdleConnections()
	client := &http.Client{Transport: tr, Timeout: 20 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("redirects disabled") }}
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, errors.New("invalid subscription URL")
	}
	req.Header.Set("User-Agent", "clash.meta/1.19.32 PSPortal-Android/0.3")
	res, err := client.Do(req)
	if err != nil {
		return nil, errors.New("subscription HTTPS download failed (public destination and no redirects required)")
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return nil, errors.New("subscription server did not return HTTP 200")
	}
	body, err := io.ReadAll(io.LimitReader(res.Body, profileLimit+1))
	if err != nil || len(body) == 0 || len(body) > profileLimit {
		return nil, errors.New("subscription read failed or exceeds 10 MiB")
	}
	return body, nil
}

// Hook is process-local, never a system network setting. It validates the final
// numeric address after DNS, including adapter-specific secondary TCP endpoints.
func guardSocketDestination(network, address string) error {
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return engine.ErrDestinationDenied
	}
	if port == "0" && (host == "" || host == "0.0.0.0" || host == "::") && (network == "udp" || network == "udp4" || network == "udp6") {
		return nil
	}
	if engine.Destination(host) != "external" {
		return engine.ErrDestinationDenied
	}
	return nil
}

type publicResolver struct{}

func (publicResolver) LookupIP(ctx context.Context, host string) ([]netip.Addr, error) {
	return publicAddresses(ctx, host)
}
func (publicResolver) LookupIPv4(ctx context.Context, host string) ([]netip.Addr, error) {
	return lookupFamily(ctx, host, true)
}
func (publicResolver) LookupIPv6(ctx context.Context, host string) ([]netip.Addr, error) {
	return lookupFamily(ctx, host, false)
}
func lookupFamily(ctx context.Context, host string, v4 bool) ([]netip.Addr, error) {
	ips, err := publicAddresses(ctx, host)
	if err != nil {
		return nil, err
	}
	out := []netip.Addr{}
	for _, ip := range ips {
		ip = ip.Unmap()
		if ip.Is4() == v4 {
			out = append(out, ip)
		}
	}
	if len(out) == 0 {
		return nil, engine.ErrResolutionFailed
	}
	return out, nil
}
func (publicResolver) ResolveECH(context.Context, string) ([]byte, error) {
	return nil, errors.New("ECH DNS discovery is unsupported")
}
func (publicResolver) ExchangeContext(context.Context, *dns.Msg) (*dns.Msg, error) {
	return nil, errors.New("arbitrary DNS exchanges are unsupported")
}
func (publicResolver) Invalid() bool    { return true }
func (publicResolver) ClearCache()      {}
func (publicResolver) ResetConnection() {}

// filteredResolver keeps VPN endpoint/direct lookups on the configured core
// resolver, while enforcing the same public-only answer boundary.
type filteredResolver struct{ resolver.Resolver }

func filterAnswers(ips []netip.Addr, err error) ([]netip.Addr, error) {
	if err != nil {
		return nil, err
	}
	if len(ips) == 0 {
		return nil, engine.ErrResolutionFailed
	}
	for _, ip := range ips {
		if engine.Destination(ip.Unmap().String()) != "external" {
			return nil, engine.ErrDestinationDenied
		}
	}
	return ips, nil
}
func (r filteredResolver) LookupIP(ctx context.Context, host string) ([]netip.Addr, error) {
	return filterAnswers(r.Resolver.LookupIP(ctx, host))
}
func (r filteredResolver) LookupIPv4(ctx context.Context, host string) ([]netip.Addr, error) {
	return filterAnswers(r.Resolver.LookupIPv4(ctx, host))
}
func (r filteredResolver) LookupIPv6(ctx context.Context, host string) ([]netip.Addr, error) {
	return filterAnswers(r.Resolver.LookupIPv6(ctx, host))
}
