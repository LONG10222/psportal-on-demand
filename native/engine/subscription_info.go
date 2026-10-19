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

const subscriptionInfoUnavailable = `{"available":false}`

// SubscriptionInfo fetches accounting headers only. It never starts a listener,
// reads another app's settings, follows redirects, or writes the subscription.
// Standalone callers retain the bounded request lifetime; mobile callers use the
// engine method so Stop also cancels their metadata requests.
func SubscriptionInfo(rawURL string) string {
	return subscriptionInfoWithContext(context.Background(), rawURL)
}

// SubscriptionInfo fetches metadata only for this running engine's configured
// subscription. It shares the core lifetime without blocking Stop on a lock.
func (e *Engine) SubscriptionInfo(rawURL string) string {
	core, err := e.liveCore()
	if err != nil || rawURL != core.cfg.SubscriptionURL {
		return subscriptionInfoUnavailable
	}
	return subscriptionInfoWithContext(core.ctx, rawURL)
}

func subscriptionInfoWithContext(ctx context.Context, rawURL string) string {
	transport := &http.Transport{Proxy: nil, DialContext: publicTCPDial,
		TLSHandshakeTimeout: 4 * time.Second, ResponseHeaderTimeout: 5 * time.Second,
		MaxResponseHeaderBytes: 65536, DisableKeepAlives: true}
	defer transport.CloseIdleConnections()
	return requestSubscriptionInfo(ctx, rawURL, transport)
}

// The transport argument keeps cancellation tests independent of DNS and public
// servers. Production callers always use the restricted transport above.
func requestSubscriptionInfo(parent context.Context, rawURL string, transport http.RoundTripper) string {
	if parent.Err() != nil || !validHTTPS(rawURL) {
		return subscriptionInfoUnavailable
	}
	ctx, cancel := context.WithTimeout(parent, 8*time.Second)
	defer cancel()
	client := &http.Client{Transport: transport, Timeout: 8 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("redirect disabled") }}
	for _, method := range []string{http.MethodHead, http.MethodGet} {
		if ctx.Err() != nil {
			return subscriptionInfoUnavailable
		}
		request, err := http.NewRequestWithContext(ctx, method, rawURL, nil)
		if err != nil {
			return subscriptionInfoUnavailable
		}
		request.Header.Set("User-Agent", "clash.meta/1.19.32 PSPortal-Native/0.2")
		response, err := client.Do(request)
		if err != nil {
			return subscriptionInfoUnavailable
		}
		response.Body.Close()
		if ctx.Err() != nil {
			return subscriptionInfoUnavailable
		}
		if response.StatusCode == http.StatusOK {
			info := parseSubscriptionInfo(response.Header.Get("subscription-userinfo"))
			if len(info) > 0 {
				raw, _ := json.Marshal(info)
				return string(raw)
			}
		} else if response.StatusCode != http.StatusMethodNotAllowed && response.StatusCode != http.StatusNotImplemented {
			return subscriptionInfoUnavailable
		}
	}
	return subscriptionInfoUnavailable
}
