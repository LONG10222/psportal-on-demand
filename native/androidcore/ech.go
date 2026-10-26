// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/miekg/dns"
	"github.com/psportal/psportal/native/engine"
)

// ECH may carry an inline TLS configuration or a DNS name. It cannot introduce
// arbitrary resolver URLs, files, routing controls or private address targets.
func validECHOptions(value any) bool {
	options, ok := value.(map[string]any)
	if !ok {
		return false
	}
	for key, value := range options {
		switch key {
		case "enable":
			if _, ok := value.(bool); !ok {
				return false
			}
		case "config":
			text, ok := value.(string)
			if !ok || len(text) > 65536 {
				return false
			}
			if _, err := base64.StdEncoding.DecodeString(text); err != nil {
				return false
			}
		case "query-server-name":
			host, ok := value.(string)
			if !ok || len(host) > 253 || (host != "" && engine.Destination(host) != "name") {
				return false
			}
		default:
			return false
		}
	}
	return true
}

func resolvePublicECH(parent context.Context, host string) ([]byte, error) {
	if len(host) > 253 || engine.Destination(host) != "name" {
		return nil, engine.ErrDestinationDenied
	}
	ctx, cancel := context.WithTimeout(parent, 8*time.Second)
	defer cancel()
	query := new(dns.Msg)
	query.SetQuestion(dns.Fqdn(host), dns.TypeHTTPS)
	wire, err := query.Pack()
	if err != nil {
		return nil, err
	}
	// Numeric HTTPS endpoint avoids a bootstrap DNS or subscription-supplied URL.
	// Normal certificate verification checks the IP SAN; no custom trust bypass.
	transport := &http.Transport{Proxy: nil, DialContext: publicDial, TLSHandshakeTimeout: 4 * time.Second, ResponseHeaderTimeout: 5 * time.Second, MaxResponseHeaderBytes: 8192, DisableKeepAlives: true}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 8 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("ECH DNS redirects disabled") }}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "https://1.1.1.1/dns-query", bytes.NewReader(wire))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/dns-message")
	request.Header.Set("Accept", "application/dns-message")
	response, err := client.Do(request)
	if err != nil {
		return nil, errors.New("ECH DNS request failed")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || strings.Split(response.Header.Get("Content-Type"), ";")[0] != "application/dns-message" {
		return nil, errors.New("invalid ECH DNS response")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, 65537))
	if err != nil || len(body) > 65536 {
		return nil, errors.New("invalid ECH DNS size")
	}
	return parsePublicECH(body, query)
}

func parsePublicECH(wire []byte, query *dns.Msg) ([]byte, error) {
	var response dns.Msg
	if response.Unpack(wire) != nil || !response.Response || response.Truncated || response.Id != query.Id || response.Rcode != dns.RcodeSuccess || len(response.Question) != 1 || response.Question[0] != query.Question[0] {
		return nil, errors.New("invalid ECH DNS answer")
	}
	for _, answer := range response.Answer {
		record, ok := answer.(*dns.HTTPS)
		if !ok || !strings.EqualFold(record.Hdr.Name, query.Question[0].Name) || record.Hdr.Class != dns.ClassINET {
			continue
		}
		for _, value := range record.Value {
			if config, ok := value.(*dns.SVCBECHConfig); ok && len(config.ECH) > 0 && len(config.ECH) <= 65535 {
				return append([]byte(nil), config.ECH...), nil
			}
		}
	}
	return nil, errors.New("ECH DNS configuration unavailable")
}
