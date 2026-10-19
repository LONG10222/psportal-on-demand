// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/metacubex/mihomo/component/dialer"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/hub/executor"
)

func groupProfileBody() []byte {
	return []byte(`{"proxies":[{"name":"A","type":"http","server":"8.8.8.8","port":8080},{"name":"B","type":"http","server":"1.1.1.1","port":8080}],"proxy-groups":[{"name":"Choice","type":"select","proxies":["A","B"]},{"name":"Nested","type":"select","proxies":["Choice","DIRECT","REJECT"]},{"name":"Fallback","type":"fallback","proxies":["A","B"]}],"rules":["MATCH,Nested"]}`)
}
func preparedGroupEngine(t *testing.T, body []byte) *Engine {
	t.Helper()
	cfg := testConfig()
	cfg.LANEnabled = false // No ingress listener or VPN; all health dials are denied below.
	e, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	e.loader = func(context.Context, string) ([]byte, error) { return body, nil }
	if err = e.Start(); err != nil {
		t.Fatal(err)
	}
	// ApplyConfig starts automatic health checks even for lazy groups. Keep
	// these selector/lifecycle fixtures entirely offline, including idle reload.
	oldHook := dialer.DefaultSocketHook
	dialer.DefaultSocketHook = func(string, string, syscall.RawConn) error { return errors.New("offline group fixture") }
	t.Cleanup(func() { e.Stop(); dialer.DefaultSocketHook = oldHook })
	if err = e.Prepare(); err != nil {
		t.Fatal(err)
	}
	return e
}
func groupOptions(t *testing.T, e *Engine, name string) map[string]any {
	t.Helper()
	text, err := e.GroupChoices(name)
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err = json.Unmarshal([]byte(text), &got); err != nil {
		t.Fatal(err)
	}
	return got
}
func TestFullProfileGroupChoicesAndSelection(t *testing.T) {
	e := preparedGroupEngine(t, groupProfileBody())
	got := groupOptions(t, e, "Choice")
	if got["group"] != "Choice" || got["selected"] != "A" || len(got["choices"].([]any)) != 2 {
		t.Fatalf("unexpected choices: %v", got)
	}
	if err := e.SelectGroup("Choice", "B"); err != nil {
		t.Fatal(err)
	}
	if groupOptions(t, e, "Choice")["selected"] != "B" {
		t.Fatal("actual Mihomo selector did not switch")
	}
	if groupOptions(t, e, "Nested")["selected"] != "Choice" {
		t.Fatal("unrelated outer policy was overwritten")
	}
	if e.cfg.SelectionMode != "auto" || e.cfg.RoutingMode != "rule" {
		t.Fatal("group choice overwrote profile/routing mode")
	}
	for _, choice := range []string{"DIRECT", "REJECT", "Choice"} {
		if err := e.SelectGroup("Nested", choice); err != nil {
			t.Fatalf("explicit member %s rejected: %v", choice, err)
		}
	}
	var status map[string]any
	if err := json.Unmarshal([]byte(e.Status()), &status); err != nil {
		t.Fatal(err)
	}
	if status["node_management"] != false || status["group_management"] != true {
		t.Fatalf("wrong capabilities: %v", status)
	}
	for _, raw := range status["policy_groups"].([]any) {
		group := raw.(map[string]any)
		if _, exists := group["choices"]; exists {
			t.Fatal("status multiplied full group choices into its bounded payload")
		}
		if group["name"] == "Fallback" && group["selectable"] != false {
			t.Fatal("automatic group was exposed as a manual selector")
		}
	}
}
func TestGroupSelectionRejectsOutsideMembershipAndAutomaticGroups(t *testing.T) {
	e := preparedGroupEngine(t, groupProfileBody())
	for _, pair := range [][2]string{{"Choice", "DIRECT"}, {"Choice", "Nested"}, {"Choice", "missing"}, {"Fallback", "B"}, {"missing", "A"}, {"Choice\n", "A"}, {"Choice", "A\n"}} {
		if err := e.SelectGroup(pair[0], pair[1]); err == nil {
			t.Fatalf("invalid group choice accepted: %q", pair)
		}
	}
	if groupOptions(t, e, "Choice")["selected"] != "A" || len(e.groupSelections) != 0 {
		t.Fatal("rejected choices changed runtime or saved session selection")
	}
	for _, name := range []string{"Fallback", "missing", ""} {
		if _, err := e.GroupChoices(name); err == nil {
			t.Fatalf("nonselectable group %q has manual choices", name)
		}
	}
}
func TestGroupSelectionKeepsActiveAndVPNGuards(t *testing.T) {
	e := preparedGroupEngine(t, groupProfileBody())
	if _, err := e.Acquire(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := e.SelectGroup("Choice", "B"); err == nil {
		t.Fatal("selection changed with an active connection")
	}
	e.Release()
	phoneSession.Lock()
	phoneSession.owner = e
	phoneSession.closer = io.NopCloser(strings.NewReader(""))
	phoneSession.Unlock()
	if err := e.SelectGroup("Choice", "B"); err == nil {
		t.Fatal("selection changed during phone VPN")
	}
	phoneSession.Lock()
	phoneSession.owner = nil
	phoneSession.closer = nil
	phoneSession.Unlock()
	if groupOptions(t, e, "Choice")["selected"] != "A" {
		t.Fatal("blocked changes altered the selector")
	}
}
func TestGroupSelectionsSurviveIdleButNotStop(t *testing.T) {
	e := preparedGroupEngine(t, groupProfileBody())
	if err := e.SelectGroup("Choice", "B"); err != nil {
		t.Fatal(err)
	}
	e.mu.Lock()
	e.unloadLocked()
	e.mu.Unlock()
	if groupOptions(t, e, "Choice")["selected"] != "B" {
		t.Fatal("idle reload silently discarded the explicit group choice")
	}
	e.Stop()
	if len(e.groupSelections) != 0 {
		t.Fatal("Stop retained session-only group choices")
	}
	if err := e.SelectGroup("Choice", "A"); err == nil {
		t.Fatal("stopped engine accepted stale group command")
	}
	next := preparedGroupEngine(t, groupProfileBody())
	if groupOptions(t, next, "Choice")["selected"] != "A" {
		t.Fatal("new session inherited a previous profile choice")
	}
}
func TestGeneratedNodePoliciesRemainSeparateFromProfileGroups(t *testing.T) {
	e := preparedGroupEngine(t, testBody())
	if _, err := e.GroupChoices(generatedGroup); err == nil {
		t.Fatal("generated simple policy was exposed as a full-profile group")
	}
	if err := e.SelectGroup(generatedGroup, "A"); err == nil {
		t.Fatal("group command bypassed generated-node mode management")
	}
	if err := e.SelectNodeWithThreshold("fixed", "A", e.cfg.SwitchThresholdMS); err != nil {
		t.Fatalf("existing simple-node control regressed: %v", err)
	}
}

// Actual Mihomo rule matching and HTTP adapters must follow the changed nested
// selector. Private test endpoints are injected only after production validation.
func TestGroupSelectionChangesActualMihomoRoute(t *testing.T) {
	oldHook := dialer.DefaultSocketHook
	dialer.DefaultSocketHook = nil
	defer func() { dialer.DefaultSocketHook = oldHook }()
	proxy := func(label string) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method != "CONNECT" {
				t.Errorf("expected CONNECT, got %s", r.Method)
				return
			}
			conn, rw, err := w.(http.Hijacker).Hijack()
			if err != nil { return }
			defer conn.Close()
			fmt.Fprint(rw, "HTTP/1.1 200 Connection Established\r\n\r\n")
			rw.Flush()
			req, err := http.ReadRequest(rw.Reader)
			if err != nil { return }
			req.Body.Close()
			fmt.Fprintf(rw, "HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s", len(label), label)
			rw.Flush()
		}))
	}
	a, b := proxy("A"), proxy("B")
	defer a.Close()
	defer b.Close()
	cfg := testConfig()
	p, err := sanitizeProfile(groupProfileBody(), cfg)
	if err != nil { t.Fatal(err) }
	for i, server := range []*httptest.Server{a, b} {
		host, port, _ := net.SplitHostPort(strings.TrimPrefix(server.URL, "http://"))
		n, _ := strconv.Atoi(port)
		p.raw.Proxy[i]["server"] = host
		p.raw.Proxy[i]["port"] = n
	}
	parsed, err := MC.ParseRawConfig(p.raw)
	if err != nil { t.Fatal(err) }
	if err = installUDPGuards(parsed); err != nil { t.Fatal(err) }
	executor.ApplyConfig(parsed, true)
	activateRuntime(parsed)
	e, _ := New(cfg)
	e.current, e.profile, e.state = parsed, p, "running"
	defer func() { e.cancel(); e.wg.Wait(); e.mu.Lock(); e.unloadLocked(); e.mu.Unlock() }()
	for _, expected := range []string{"A", "B", "A"} {
		if err = e.SelectGroup("Choice", expected); err != nil { t.Fatal(err) }
		conn, err := e.openTunnel(context.Background(), &C.Metadata{NetWork: C.TCP, Type: C.HTTP, DstIP: netip.MustParseAddr("8.8.4.4"), DstPort: 443})
		if err != nil { t.Fatal(err) }
		conn.SetDeadline(time.Now().Add(3 * time.Second))
		fmt.Fprint(conn, "GET / HTTP/1.1\r\nHost: fixture.invalid\r\nConnection: close\r\n\r\n")
		res, err := http.ReadResponse(bufio.NewReader(conn), nil)
		if err != nil { conn.Close(); t.Fatal(err) }
		body, err := io.ReadAll(res.Body)
		res.Body.Close()
		conn.Close()
		if err != nil || string(body) != expected { t.Fatalf("route = %q, error %v; want %s", body, err, expected) }
	}
}
