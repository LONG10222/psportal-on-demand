// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func commandResult(t *testing.T, raw, code string, ok bool) {
	t.Helper()
	var result struct {
		OK   bool   `json:"ok"`
		Code string `json:"code"`
	}
	if err := json.Unmarshal([]byte(raw), &result); err != nil || result.OK != ok || result.Code != code {
		t.Fatalf("unexpected command result %q: %v", raw, err)
	}
}

func TestNodeCommandAndNativeSelectionSharePolicy(t *testing.T) {
	cfg := validConfig()
	cfg.HealthURL = "http://8.8.8.8/health"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	var first, second atomic.Int32
	a, b := healthFixtureNode("A", &first), healthFixtureNode("B", &second)
	a.healthy, a.delayMS, a.protocol = true, 100, "socks5"
	b.healthy, b.delayMS, b.protocol = true, 200, "trojan"
	c.mu.Lock()
	c.nodes = []*node{a, b}
	c.updateHealthLocked(true)
	c.mu.Unlock()
	e := &Engine{core: c, running: true}

	// The existing iOS select command trusts a measured healthy node, without
	// adding a probe, and the richer runtime observes that same fixed policy.
	commandResult(t, e.NodeCommand(`{"action":"select","name":"B"}`), "done", true)
	if s := c.Status(); s["manual_node"] != "B" || s["auto_fastest"] != false || s["selection_mode"] != "fixed" || s["selected_node"] != "B" {
		t.Fatal(s)
	}
	if first.Load() != 0 || second.Load() != 0 {
		t.Fatal("legacy selection unexpectedly probed")
	}
	commandResult(t, e.NodeCommand(`{"action":"fastest"}`), "done", true)
	if first.Load() != 1 || second.Load() != 1 {
		t.Fatal("fastest did not test the full pool exactly once")
	}
	if s := c.Status(); s["manual_node"] != "" || s["auto_fastest"] != true || s["selection_mode"] != "fastest" {
		t.Fatal(s)
	}
	c.mu.Lock()
	a.delayMS, b.delayMS = 10, 100
	c.updateHealthLocked(true)
	b.delayMS = 0 // A successful sub-millisecond measurement is valid.
	c.updateHealthLocked(true)
	c.mu.Unlock()
	if s := c.Status(); s["selected_node"] != "B" {
		t.Fatal("iOS lowest-latency mode gained a threshold or hold-down", s)
	}

	if err := c.changeSelection("auto", "", nil, false); err != nil {
		t.Fatal(err)
	}
	if s := c.Status(); s["manual_node"] != "" || s["auto_fastest"] != false || s["selection_mode"] != "auto" {
		t.Fatal("native mode change left stale iOS flags", s)
	}
	if err := c.changeSelection("fixed", "A", nil, false); err != nil {
		t.Fatal(err)
	}
	if s := c.Status(); s["manual_node"] != "A" || s["auto_fastest"] != false {
		t.Fatal(s)
	}
	c.mu.Lock()
	legacy := c.legacyFastest
	c.mu.Unlock()
	if legacy {
		t.Fatal("native selection retained the legacy fastest policy")
	}
	list := c.Status()["nodes"].([]map[string]any)
	if list[0]["protocol"] != "socks5" || list[1]["protocol"] != "trojan" {
		t.Fatal("iOS protocol labels missing", list)
	}
}

func TestNodeCommandSharesBusyLockAndStopCancellation(t *testing.T) {
	c := newEmbeddedCore(validConfig())
	entered := make(chan struct{})
	c.loader = func(ctx context.Context, _ Config) ([]*node, error) {
		close(entered)
		<-ctx.Done()
		return nil, ctx.Err()
	}
	e := &Engine{core: c, running: true}
	prepared := make(chan error, 1)
	go func() { prepared <- e.Prepare() }()
	select {
	case <-entered:
	case <-time.After(time.Second):
		c.Close()
		t.Fatal("prepare never entered")
	}
	commandResult(t, e.NodeCommand(`{"action":"prepare"}`), "busy", false)
	c.Close()
	if err := <-prepared; err == nil {
		t.Fatal("stopped preparation succeeded")
	}
	commandResult(t, e.NodeCommand(`{"action":"prepare"}`), "stopped", false)
	for _, raw := range []string{`null`, `{}`, `{"action":"select","name":"DIRECT"}`, `{"action":"invalid"}`, strings.Repeat("x", 2049)} {
		commandResult(t, e.NodeCommand(raw), "invalid", false)
	}
}

func TestCurrentAndHistoricalClientMetricsStayDistinct(t *testing.T) {
	p := NewProxy(validConfig(), nil)
	now := time.Now().Unix()
	p.clients["192.168.1.10"] = &clientRecord{Active: 2, Accepted: 5, LastSeen: now}
	p.clients["192.168.1.20"] = &clientRecord{Accepted: 3, LastSeen: now}
	p.clients["192.168.1.30"] = &clientRecord{Accepted: 1, LastSeen: now - 301}
	p.stats["active"] = 2
	s := p.Status()
	if s["connected_clients"] != 1 || s["active_devices"] != 1 || s["active_connections"] != uint64(2) || !reflect.DeepEqual(s["client_ips"], []string{"192.168.1.10"}) {
		t.Fatal(s)
	}
	devices := s["devices"].([]map[string]any)
	if len(devices) != 2 || devices[1]["ip"] != "192.168.1.20" || devices[1]["active"] != uint64(0) || devices[1]["accepted"] != uint64(3) {
		t.Fatal("recent device history was lost or counted as connected", devices)
	}
}
