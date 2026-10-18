// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"strings"
	"testing"
)

func TestDestination(t *testing.T) {
	cases := map[string][]string{
		"local":    {"10.20.0.1", "172.16.0.1", "172.31.255.254", "192.168.50.1", "fc12::1", "fd12::1"},
		"external": {"8.8.8.8", "1.1.1.1", "172.15.0.1", "172.32.0.1", "100.63.255.255", "100.128.0.1", "2001:200::1", "2001:4860:4860::8888", "2606:4700:4700::1111", "3fff:1000::1"},
		"name":     {"example.com", "printer.lan", "fc-example.com", "a", "EXAMPLE.COM.", "123.example"},
		"deny":     {"0.0.0.0", "0.1.2.3", "127.0.0.1", "127.255.255.255", "169.254.169.254", "100.64.0.1", "100.127.255.254", "192.0.0.9", "192.0.2.1", "192.88.99.1", "198.18.0.1", "198.19.255.255", "198.51.100.1", "203.0.113.1", "224.0.0.1", "239.255.255.255", "240.0.0.1", "255.255.255.255", "::", "::1", "fe80::1", "ff02::1", "fec0::1", "::ffff:192.168.1.1", "::ffff:8.8.8.8", "::8.8.8.8", "64:ff9b::808:808", "2001::1", "2001:1ff::1", "2001:db8::1", "2002:808:808::1", "3fff:fff::1", "4000::1", "ffff::1", "", "localhost", "a.localhost", "LOCALHOST.", "127.1", "2130706433", "0177.0.0.1", "0x7f000001", "0x7f.1", "1.2.3.4.5", "01.2.3.4", "999.1.2.3", "1..2", ".example.com", "example..com", "foo-", "-foo", "foo_bar", "eä.com", "1.2.3.-1", "fe80::1%eth0", "[::1]", "1:2:3", "::ffff:01.2.3.4", strings.Repeat("a", 64) + ".com"},
	}
	for want, hosts := range cases {
		for _, host := range hosts {
			t.Run(host, func(t *testing.T) {
				if got := Destination(host); got != want {
					t.Errorf("Destination(%q)=%s want %s", host, got, want)
				}
			})
		}
	}
}
func TestBackendRejectRules(t *testing.T) {
	rules := BackendRejectRules()
	if rules[0] != "DOMAIN-SUFFIX,localhost,REJECT" {
		t.Fatal(rules)
	}
	for _, rule := range rules {
		if strings.Contains(rule, "DIRECT") || strings.Contains(rule, "no-resolve") {
			t.Fatal(rule)
		}
	}
	if !strings.Contains(strings.Join(rules, "\n"), "IP-CIDR6,8000::/1,REJECT") {
		t.Fatal(rules)
	}
}

type fakeResolver struct {
	answers []net.IPAddr
	err     error
	calls   int
}

func (r *fakeResolver) LookupIPAddr(context.Context, string) ([]net.IPAddr, error) {
	r.calls++
	return r.answers, r.err
}
func fixtureAnswers(addresses ...string) []net.IPAddr {
	var answers []net.IPAddr
	for _, s := range addresses {
		a := netip.MustParseAddr(s)
		answers = append(answers, net.IPAddr{IP: a.AsSlice()})
	}
	return answers
}
func TestResolveDestination(t *testing.T) {
	tests := []struct {
		name                 string
		answers              []net.IPAddr
		lookupErr, errorKind error
		want                 Route
	}{
		{"all local", fixtureAnswers("192.168.1.2", "fd00::1"), nil, nil, Route{"local", "192.168.1.2"}},
		{"public", fixtureAnswers("8.8.8.8"), nil, nil, Route{"external", ""}},
		{"mixed", fixtureAnswers("192.168.1.2", "8.8.8.8"), nil, nil, Route{"external", ""}},
		{"public then denied", fixtureAnswers("8.8.8.8", "127.0.0.1"), nil, ErrDestinationDenied, Route{}},
		{"denied then public", fixtureAnswers("127.0.0.1", "8.8.8.8"), nil, ErrDestinationDenied, Route{}},
		{"local then denied", fixtureAnswers("192.168.1.2", "::1"), nil, ErrDestinationDenied, Route{}},
		{"metadata", fixtureAnswers("8.8.8.8", "169.254.169.254"), nil, ErrDestinationDenied, Route{}},
		{"mapped", fixtureAnswers("::ffff:8.8.8.8"), nil, ErrDestinationDenied, Route{}},
		{"empty", nil, nil, ErrResolutionFailed, Route{}},
		{"NXDOMAIN", nil, errors.New("NXDOMAIN"), ErrResolutionFailed, Route{}},
		{"malformed", []net.IPAddr{{IP: []byte{1, 2}}}, nil, ErrResolutionFailed, Route{}},
		{"scoped", []net.IPAddr{{IP: netip.MustParseAddr("fd00::1").AsSlice(), Zone: "en0"}}, nil, ErrDestinationDenied, Route{}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			resolver := &fakeResolver{answers: test.answers, err: test.lookupErr}
			got, err := resolveDestination(context.Background(), resolver, "fixture.example", 80)
			if !errors.Is(err, test.errorKind) || got != test.want {
				t.Fatalf("got %+v %v; want %+v %v", got, err, test.want, test.errorKind)
			}
		})
	}
}
func TestResolveLiteralsSkipDNS(t *testing.T) {
	r := &fakeResolver{err: errors.New("DNS must not run")}
	for _, host := range []string{"8.8.8.8", "192.168.1.2", "127.0.0.1"} {
		_, _ = resolveDestination(context.Background(), r, host, 80)
	}
	if r.calls != 0 {
		t.Fatal("literal used DNS")
	}
}
