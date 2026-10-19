// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"github.com/metacubex/mihomo/component/dialer"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/hub/executor"
	"github.com/metacubex/mihomo/tunnel"
	"github.com/psportal/psportal/native/engine"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func testConfig() Config {
	c := engine.DefaultConfig()
	c.ListenHost = "127.0.0.1"
	c.AllowedClients = []string{"127.0.0.1"}
	c.SubscriptionURL = "https://subscription.example/profile"
	return Config{Config: c, RoutingMode: "rule", LANEnabled: true}
}
func testBody() []byte {
	return []byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080}]}`)
}

// These tests run upstream config parsing, executor, rule matcher, selector and
// HTTP adapters. Loopback endpoints are injected AFTER production sanitization
// solely into the private fixture; no production endpoint allowlist is relaxed.
func TestRealFullCoreRuleGlobalDirect(t *testing.T) {
	oldHook := dialer.DefaultSocketHook
	dialer.DefaultSocketHook = nil
	defer func() { dialer.DefaultSocketHook = oldHook }()
	var aHits, bHits atomic.Int32
	proxy := func(label string, hits *atomic.Int32) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method != "CONNECT" {
				t.Errorf("Mihomo HTTP adapter did not CONNECT: %s", r.Method)
				return
			}
			hits.Add(1)
			conn, rw, err := w.(http.Hijacker).Hijack()
			if err != nil {
				return
			}
			defer conn.Close()
			fmt.Fprint(rw, "HTTP/1.1 200 Connection Established\r\n\r\n")
			rw.Flush()
			req, err := http.ReadRequest(rw.Reader)
			if err != nil {
				return
			}
			req.Body.Close()
			fmt.Fprintf(rw, "HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s", len(label), label)
			rw.Flush()
		}))
	}
	a, b := proxy("proxy-A", &aHits), proxy("proxy-B", &bHits)
	defer a.Close()
	defer b.Close()
	direct := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, "direct") }))
	defer direct.Close()
	_, portText, _ := net.SplitHostPort(strings.TrimPrefix(direct.URL, "http://"))
	port, _ := strconv.Atoi(portText)
	for _, mode := range []string{"rule", "global", "direct"} {
		t.Run(mode, func(t *testing.T) {
			cfg := testConfig()
			cfg.RoutingMode = mode
			body := []byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080},{"name":"B","type":"http","server":"1.1.1.1","port":8080}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A","B"]}],"rules":["IP-CIDR,127.0.0.1/32,B,no-resolve","MATCH,A"]}`)
			p, err := sanitizeProfile(body, cfg)
			if err != nil {
				t.Fatal(err)
			}
			for i, s := range []*httptest.Server{a, b} {
				host, ptext, _ := net.SplitHostPort(strings.TrimPrefix(s.URL, "http://"))
				pn, _ := strconv.Atoi(ptext)
				p.raw.Proxy[i]["server"] = host
				p.raw.Proxy[i]["port"] = pn
			}
			parsed, err := MC.ParseRawConfig(p.raw)
			if err != nil {
				t.Fatal(err)
			}
			if err := installUDPGuards(parsed); err != nil {
				t.Fatal(err)
			}
			executor.ApplyConfig(parsed, true)
			activateRuntime(parsed)
			e, _ := New(cfg)
			e.current = parsed
			e.profile = p
			e.state = "running"
			defer func() { e.cancel(); e.wg.Wait(); e.mu.Lock(); e.unloadLocked(); e.mu.Unlock() }()
			conn, err := e.openTunnel(context.Background(), &C.Metadata{NetWork: C.TCP, Type: C.HTTP, DstIP: netip.MustParseAddr("127.0.0.1"), DstPort: uint16(port)})
			if err != nil {
				t.Fatal(err)
			}
			conn.SetDeadline(time.Now().Add(3 * time.Second))
			fmt.Fprint(conn, "GET / HTTP/1.1\r\nHost: fixture.invalid\r\nConnection: close\r\n\r\n")
			res, err := http.ReadResponse(bufio.NewReader(conn), nil)
			if err != nil {
				conn.Close()
				t.Fatal(err)
			}
			got, _ := io.ReadAll(res.Body)
			res.Body.Close()
			conn.Close()
			want := map[string]string{"rule": "proxy-B", "global": "proxy-A", "direct": "direct"}[mode]
			if string(got) != want {
				t.Fatalf("mode %s routed %q, want %q", mode, got, want)
			}
			if tunnel.Mode().String() != mode {
				t.Fatalf("actual Mihomo mode=%s", tunnel.Mode())
			}
			plain, err := http.Get(direct.URL)
			if err != nil {
				t.Fatal(err)
			}
			plainBody, _ := io.ReadAll(plain.Body)
			plain.Body.Close()
			if string(plainBody) != "direct" {
				t.Fatal("ordinary host request was intercepted")
			}
		})
	}
	if aHits.Load() != 1 || bHits.Load() != 1 {
		t.Fatalf("real adapter route counts A=%d B=%d", aHits.Load(), bHits.Load())
	}
}
func TestProfileSafetyBoundary(t *testing.T) {
	cfg := testConfig()
	p, err := sanitizeProfile(testBody(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	r := p.raw
	if r.Port != 0 || r.MixedPort != 0 || r.Tun.Enable || r.DNS.Enable || r.IPTables.Enable || r.NTP.Enable || r.ExternalController != "" || r.Profile.StoreSelected {
		t.Fatal("unexpected listener/system capability")
	}
	cases := map[string]string{
		"provider":        `"proxy-providers":{"x":{"type":"http","url":"http://127.0.0.1"}}`,
		"rule provider":   `"rule-providers":{"x":{"type":"file","path":"/etc/passwd"}}`,
		"geodata":         `"rules":["GEOIP,CN,DIRECT","MATCH,A"]`,
		"script":          `"rules":["SCRIPT,thing,A","MATCH,A"]`,
		"implicit direct": `"rules":["DOMAIN,a.example,A"]`,
	}
	for name, extra := range cases {
		t.Run(name, func(t *testing.T) {
			body := strings.TrimSuffix(string(testBody()), "}") + "," + extra + "}"
			if _, err := sanitizeProfile([]byte(body), cfg); err == nil {
				t.Fatal("unsafe/unsupported feature accepted")
			}
		})
	}
	for _, option := range []string{`"ip":"127.0.0.1"`, `"xhttp-opts":{"download-settings":{"server":"127.0.0.1"}}`, `"realm-opts":{"server-url":"http://127.0.0.1"}`, `"client-key":"/etc/passwd"`, `"dialer-proxy":"DIRECT"`} {
		body := strings.Replace(string(testBody()), `"port":8080`, `"port":8080,`+option, 1)
		if _, err := sanitizeProfile([]byte(body), cfg); err == nil {
			t.Fatalf("unsafe node option accepted: %s", option)
		}
	}
	for _, address := range []string{"127.0.0.1:443", "192.168.1.1:443", "169.254.169.254:80", "[::1]:443", "localhost:443"} {
		if guardSocketDestination("tcp", address) == nil {
			t.Fatalf("socket boundary allowed %s", address)
		}
	}
	if err := guardSocketDestination("tcp", "8.8.8.8:443"); err != nil {
		t.Fatal(err)
	}
}
func TestProfileIgnoresSystemSettingsBeforeParse(t *testing.T) {
	cfg := testConfig()
	body := strings.TrimSuffix(string(testBody()), "}") + `,"tun":{"enable":true,"auto-route":true},"dns":{"enable":true,"listen":"0.0.0.0:53"},"external-controller":"0.0.0.0:9090","listeners":[{"type":"tun"}],"ntp":{"enable":true,"write-to-system":true},"hosts":{"public.example":"127.0.0.1"},"iptables":{"enable":true},"interface-name":"bad","external-ui-url":"http://127.0.0.1"}`
	p, err := sanitizeProfile([]byte(body), cfg)
	if err != nil {
		t.Fatal(err)
	}
	if p.raw.Tun.Enable || p.raw.DNS.Enable || p.raw.ExternalController != "" || p.raw.Listeners != nil || p.raw.NTP.Enable || p.raw.IPTables.Enable || len(p.raw.Hosts) != 0 || p.raw.Interface != "" || p.raw.ExternalUIURL != "" {
		t.Fatal("source system settings escaped sanitizer")
	}
}
func TestConfigModesAndIndependentScopes(t *testing.T) {
	for _, mode := range []string{"rule", "global", "direct"} {
		for _, pair := range [][2]bool{{true, false}, {false, true}, {true, true}} {
			cfg := testConfig()
			raw, _ := json.Marshal(cfg.Config)
			var values map[string]any
			json.Unmarshal(raw, &values)
			values["routing_mode"] = mode
			values["lan_enabled"] = pair[0]
			values["phone_vpn"] = pair[1]
			if !pair[0] {
				values["listen_host"] = ""
				values["allowed_clients"] = []string{}
			}
			raw, _ = json.Marshal(values)
			got, err := ParseConfig(string(raw))
			if err != nil {
				t.Fatal(err)
			}
			if got.RoutingMode != mode || got.LANEnabled != pair[0] || got.PhoneVPN != pair[1] {
				t.Fatal("mode/session option lost")
			}
		}
	}
	raw, _ := json.Marshal(testConfig().Config)
	text := strings.TrimSuffix(string(raw), "}")
	for _, extra := range []string{`,"routing_mode":"fake"}`, `,"lan_enabled":false,"phone_vpn":false}`, `,"phone_vpn":"yes"}`} {
		if _, err := ParseConfig(text + extra); err == nil {
			t.Fatal("invalid mode/scope accepted")
		}
	}
}
func TestLifecycleCancelAndRestart(t *testing.T) {
	cfg := testConfig()
	cfg.LANEnabled = false
	cfg.PhoneVPN = true
	e, _ := New(cfg)
	started := make(chan struct{})
	e.loader = func(ctx context.Context, _ string) ([]byte, error) {
		close(started)
		<-ctx.Done()
		return nil, ctx.Err()
	}
	if err := e.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- e.Prepare() }()
	<-started
	stopped := make(chan struct{})
	go func() { e.Stop(); close(stopped) }()
	select {
	case <-stopped:
	case <-time.After(time.Second):
		t.Fatal("Stop did not cancel subscription load")
	}
	if <-done == nil {
		t.Fatal("cancelled load succeeded")
	}
	if e.proxy != nil {
		t.Fatal("VPN-only session bound a LAN listener")
	}
	next, _ := New(cfg)
	if err := next.Start(); err != nil {
		t.Fatal(err)
	}
	next.Stop()
}
func TestFailedSourceNeverStartsTunnel(t *testing.T) {
	cfg := testConfig()
	cfg.LANEnabled = false
	cfg.PhoneVPN = true
	e, _ := New(cfg)
	e.loader = func(context.Context, string) ([]byte, error) { return []byte(`<html>invalid profile</html>`), nil }
	if err := e.Start(); err != nil {
		t.Fatal(err)
	}
	defer e.Stop()
	if e.Prepare() == nil || e.current != nil {
		t.Fatal("invalid profile activated")
	}
	if _, err := e.DialExternal(context.Background(), "127.0.0.1", 80); err == nil {
		t.Fatal("failed core allowed a direct fallback")
	}
}
func TestProfileOwnedGroupRejectsConflictingNodePreference(t *testing.T) {
	cfg := testConfig()
	cfg.SelectionMode = "fixed"
	cfg.PreferredNode = "A"
	body := strings.TrimSuffix(string(testBody()), "}") + `,"proxy-groups":[{"name":"Policy","type":"select","proxies":["A"]}],"rules":["MATCH,Policy"]}`
	if _, err := sanitizeProfile([]byte(body), cfg); err == nil {
		t.Fatal("fixed silently ignored for profile-owned group")
	}
}

func TestExplicitUDPRestrictionsArePreserved(t *testing.T) {
	cfg := testConfig()
	cfg.PhoneVPN = true
	body := []byte(`{"proxies":[{"name":"A","type":"socks5","server":"8.8.8.8","port":8080,"udp":false}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A"],"disable-udp":true}],"rules":["MATCH,Choice"]}`)
	p, err := sanitizeProfile(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if p.raw.Proxy[0]["udp"] != false || p.raw.ProxyGroup[0]["disable-udp"] != true {
		t.Fatal("explicit UDP opt-out was overwritten")
	}
	parsed, err := MC.ParseRawConfig(p.raw)
	if err != nil {
		t.Fatal(err)
	}
	defer closeConfig(parsed)
	if err = installUDPGuards(parsed); err != nil {
		t.Fatal(err)
	}
	activateRuntime(parsed)
	m := &C.Metadata{NetWork: C.UDP, DstIP: netip.MustParseAddr("8.8.4.4"), DstPort: 443}
	for _, name := range []string{"A", "Choice"} {
		if !parsed.Proxies[name].SupportUDP() {
			t.Fatal("matcher guard did not prevent skip")
		}
		if pc, err := parsed.Proxies[name].ListenPacketContext(context.Background(), m); err == nil {
			if pc != nil {
				pc.Close()
			}
			t.Fatalf("explicit UDP opt-out ignored for %s", name)
		}
	}
}

func TestLoadedProfileIdleRewakeAndOwnedListener(t *testing.T) {
	cfg := testConfig()
	portListener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	cfg.ListenPort = portListener.Addr().(*net.TCPAddr).Port
	portListener.Close()
	cfg.IdleSeconds = 1
	e, _ := New(cfg)
	var downloads atomic.Int32
	body := []byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A"]}],"rules":["MATCH,Choice"]}`)
	e.loader = func(context.Context, string) ([]byte, error) { downloads.Add(1); return body, nil }
	if err = e.Start(); err != nil {
		t.Fatal(err)
	}
	defer e.Stop()
	if downloads.Load() != 0 {
		t.Fatal("Start fetched subscription without traffic/prepare")
	}
	if err = e.Prepare(); err != nil {
		t.Fatal(err)
	}
	var status map[string]any
	if err = json.Unmarshal([]byte(e.Status()), &status); err != nil {
		t.Fatal(err)
	}
	if status["engine"] != "mihomo-full-core" || status["routing_mode"] != "rule" || status["node_management"] != false {
		t.Fatalf("incorrect real core status: %#v", status)
	}
	groups := status["policy_groups"].([]any)
	if len(groups) != 2 {
		t.Fatalf("expected actual Choice and GLOBAL groups, got %#v", groups)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		e.mu.Lock()
		asleep := e.current == nil
		e.mu.Unlock()
		if asleep {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	e.mu.Lock()
	asleep := e.current == nil
	e.mu.Unlock()
	if !asleep {
		t.Fatal("idle core did not unload")
	}
	if err = e.Prepare(); err != nil {
		t.Fatal(err)
	}
	if downloads.Load() != 1 {
		t.Fatal("idle rewake unexpectedly refetched the subscription")
	}
	e.Stop()
	if conn, err := net.DialTimeout("tcp", net.JoinHostPort(cfg.ListenHost, strconv.Itoa(cfg.ListenPort)), time.Second); err == nil {
		conn.Close()
		t.Fatal("Stop left owned LAN listener running")
	}
}
