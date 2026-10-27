// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"github.com/miekg/dns"
	"testing"
)

func TestECHOptionsAndDNSBoundary(t *testing.T) {
	for _, value := range []any{map[string]any{"enable": true, "query-server-name": "example.com"}, map[string]any{"enable": true, "config": "AQID"}, map[string]any{"enable": false}} {
		if !validECHOptions(value) || unsafeOptions(map[string]any{"ech-opts": value}) {
			t.Fatal("bounded ECH option rejected")
		}
	}
	for _, value := range []any{"invalid", map[string]any{"enable": "true"}, map[string]any{"config": "%%%"}, map[string]any{"query-server-name": "http://127.0.0.1/"}, map[string]any{"query-server-name": "localhost"}, map[string]any{"query-server-name": "192.168.1.1"}, map[string]any{"url": "https://example.com"}, map[string]any{"private-key": "/etc/passwd"}} {
		if validECHOptions(value) || !unsafeOptions(map[string]any{"ech-opts": value}) {
			t.Fatal("unbounded ECH option accepted")
		}
	}
	query := new(dns.Msg)
	query.SetQuestion("example.com.", dns.TypeHTTPS)
	reply := new(dns.Msg)
	reply.SetReply(query)
	record := &dns.HTTPS{SVCB: dns.SVCB{Hdr: dns.RR_Header{Name: "example.com.", Rrtype: dns.TypeHTTPS, Class: dns.ClassINET}, Priority: 1, Target: ".", Value: []dns.SVCBKeyValue{&dns.SVCBECHConfig{ECH: []byte{1, 2, 3}}}}}
	reply.Answer = []dns.RR{record}
	wire, _ := reply.Pack()
	if config, err := parsePublicECH(wire, query); err != nil || len(config) != 3 {
		t.Fatal("valid HTTPS ECH answer rejected", err)
	}
	reply.Id++
	wire, _ = reply.Pack()
	if _, err := parsePublicECH(wire, query); err == nil {
		t.Fatal("mismatched transaction accepted")
	}
	reply.SetReply(query)
	record.Hdr.Name = "other.example."
	wire, _ = reply.Pack()
	if _, err := parsePublicECH(wire, query); err == nil {
		t.Fatal("unrelated ECH owner accepted")
	}
	for _, host := range []string{"localhost", "127.0.0.1", "192.168.1.1", "https://example.com/"} {
		if _, err := resolvePublicECH(context.Background(), host); err == nil {
			t.Fatal("non-public ECH query accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := resolvePublicECH(ctx, "example.com"); err == nil {
		t.Fatal("cancelled ECH request accepted")
	}
}
