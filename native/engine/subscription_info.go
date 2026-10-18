// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func parseSubscriptionInfo(header string) map[string]uint64 {
	result := map[string]uint64{}
	if len(header) > 4096 {
		return result
	}
	for _, item := range strings.Split(header, ";") {
		key, value, ok := strings.Cut(strings.TrimSpace(item), "=")
		if !ok || (key != "upload" && key != "download" && key != "total" && key != "expire") {
			continue
		}
		number, err := strconv.ParseUint(strings.TrimSpace(value), 10, 63)
		if err == nil && (key != "expire" || number <= 253402300799) {
			result[key] = number
		}
	}
	return result
}

// SubscriptionInfo fetches accounting headers only. It never starts a listener,
// reads another app's settings, follows redirects, or writes the subscription.
func SubscriptionInfo(rawURL string) string {
	empty := `{"available":false}`
	if !validHTTPS(rawURL) {
		return empty
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	transport := &http.Transport{Proxy: nil, DialContext: publicTCPDial,
		TLSHandshakeTimeout: 4 * time.Second, ResponseHeaderTimeout: 5 * time.Second,
		MaxResponseHeaderBytes: 65536, DisableKeepAlives: true}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 8 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("redirect disabled") }}
	for _, method := range []string{http.MethodHead, http.MethodGet} {
		request, err := http.NewRequestWithContext(ctx, method, rawURL, nil)
		if err != nil {
			return empty
		}
		request.Header.Set("User-Agent", "clash.meta/1.19.32 PSPortal-Native/0.2")
		response, err := client.Do(request)
		if err != nil {
			return empty
		}
		response.Body.Close()
		if response.StatusCode == http.StatusOK {
			info := parseSubscriptionInfo(response.Header.Get("subscription-userinfo"))
			if len(info) > 0 {
				raw, _ := json.Marshal(info)
				return string(raw)
			}
		} else if response.StatusCode != http.StatusMethodNotAllowed && response.StatusCode != http.StatusNotImplemented {
			return empty
		}
	}
	return empty
}
