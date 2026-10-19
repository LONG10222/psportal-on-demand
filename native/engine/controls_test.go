// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"errors"
	C "github.com/metacubex/mihomo/constant"
	"net"
	"strings"
	"testing"
	"time"
)

func TestManualNodeSelectionNeverFallsBackAndRejectsUnknown(t *testing.T) {
	c := newEmbeddedCore(validConfig())
	defer c.Close()
	e := &Engine{core: c, running: true}
	attempts := []string{}
	makeNode := func(name string, delay int64) *node {
		return &node{healthy: true, delayMS: delay, proxy: &fakeNode{name: name, dial: func(context.Context, *C.Metadata) (C.Conn, error) {
			attempts = append(attempts, name)
			return nil, errors.New("fixture down")
		}}}
	}
	c.nodes = []*node{makeNode("slow", 80), makeNode("🇭🇰 fast", 20)}
	c.mode = "fastest"
	c.legacyFastest = true
	if got := e.NodeCommand(`{"action":"select","name":"🇭🇰 fast"}`); !strings.Contains(got, `"ok":true`) {
		t.Fatal(got)
	}
	if c.mode != "fixed" || c.preferred != "🇭🇰 fast" {
		t.Fatal("manual did not leave automatic mode")
	}
	if got := e.NodeCommand(`{"action":"select","name":"missing"}`); !strings.Contains(got, `"ok":false`) || c.preferred != "🇭🇰 fast" {
		t.Fatal("unknown name changed selection")
	}
	_, _ = c.DialExternal(context.Background(), "8.8.8.8", 443)
	if len(attempts) != 1 || attempts[0] != "🇭🇰 fast" {
		t.Fatal(attempts)
	}
}

func TestFastestRoutesHealthyNodesByDelay(t *testing.T) {
	c := newEmbeddedCore(validConfig())
	defer c.Close()
	attempts := []string{}
	for _, v := range []struct {
		name    string
		delay   int64
		healthy bool
	}{{"slow", 90, true}, {"failed", 0, false}, {"fast", 10, true}} {
		name := v.name
		c.nodes = append(c.nodes, &node{healthy: v.healthy, delayMS: v.delay, proxy: &fakeNode{name: name, dial: func(context.Context, *C.Metadata) (C.Conn, error) {
			attempts = append(attempts, name)
			return nil, errors.New("fixture")
		}}})
	}
	c.mode = "fastest"
	c.legacyFastest = true
	_, _ = c.DialExternal(context.Background(), "8.8.8.8", 443)
	if strings.Join(attempts, ",") != "fast,slow" {
		t.Fatal(attempts)
	}
}

func TestNodeCommandCancelledOnStopAndBounded(t *testing.T) {
	c := newEmbeddedCore(validConfig())
	e := &Engine{core: c, running: true}
	c.loading = make(chan struct{}) // Controlled in-flight load; no network.
	done := make(chan string, 1)
	go func() { done <- e.NodeCommand(`{"action":"prepare"}`) }()
	time.Sleep(20 * time.Millisecond)
	c.Close()
	select {
	case got := <-done:
		if !strings.Contains(got, `"ok":false`) {
			t.Fatal(got)
		}
	case <-time.After(time.Second):
		t.Fatal("stop did not cancel preparation")
	}
	if got := e.NodeCommand(strings.Repeat("x", 2049)); !strings.Contains(got, `"code":"invalid"`) {
		t.Fatal(got)
	}
}

func TestClientTelemetryCountsIPNotSocketsAndClearsOnStop(t *testing.T) {
	cfg := validConfig()
	cfg.ListenHost = "127.0.0.1"
	cfg.ListenPort = 0
	cfg.AllowedClients = []string{"127.0.0.1"}
	p := NewProxy(cfg, nil)
	if err := p.Start(); err != nil {
		t.Fatal(err)
	}
	defer p.Stop()
	address := p.Status()["listen_address"].(string)
	first, err := net.Dial("tcp4", address)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	second, err := net.Dial("tcp4", address)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	for deadline := time.Now().Add(time.Second); time.Now().Before(deadline); {
		if p.Status()["active"] == uint64(2) {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	s := p.Status()
	if s["active_devices"] != 1 || s["active"] != uint64(2) {
		t.Fatal(s)
	}
	records := s["devices"].([]map[string]any)
	if len(records) != 1 || records[0]["accepted"] != uint64(2) {
		t.Fatal(records)
	}
	_ = p.Stop()
	if len(p.Status()["devices"].([]map[string]any)) != 0 {
		t.Fatal("stop retained clients")
	}
}

func TestFailedFastestProbePreservesSelection(t *testing.T) {
	c := newEmbeddedCore(validConfig())
	defer c.Close()
	c.nodes = []*node{{proxy: &fakeNode{name: "chosen"}, healthy: true, delayMS: 20}}
	c.mode, c.preferred = "fixed", "chosen"
	e := &Engine{core: c, running: true}
	got := e.NodeCommand(`{"action":"fastest"}`)
	if !strings.Contains(got, `"ok":false`) || c.preferred != "chosen" || c.mode != "fixed" {
		t.Fatal(got)
	}
}
