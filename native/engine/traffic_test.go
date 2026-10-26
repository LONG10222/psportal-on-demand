// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"io"
	"net"
	"testing"
	"time"
)

func TestTrafficScopeCountersAndIdleRates(t *testing.T) {
	m := &TrafficMeter{}
	m.Snapshot()
	m.Add("local", true, 100)
	m.Add("external", false, 500)
	m.Add("deny", true, 900)
	m.mu.Lock()
	m.previous = time.Now().Add(-time.Second)
	m.mu.Unlock()
	s := m.Snapshot()
	if s["local"].(map[string]any)["upload_bytes"] != uint64(100) || s["external"].(map[string]any)["download_bytes"] != uint64(500) {
		t.Fatal(s)
	}
	if s["external"].(map[string]any)["download_bps"].(float64) <= 0 {
		t.Fatal("missing measured rate")
	}
	m.mu.Lock()
	m.previous = time.Now().Add(-time.Second)
	m.mu.Unlock()
	if m.Snapshot()["external"].(map[string]any)["download_bps"] != float64(0) {
		t.Fatal("idle rate did not decay")
	}
}

func TestTrafficConnBuffersUntilDestinationValidated(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	m := &TrafficMeter{}
	c := &trafficConn{Conn: a, meter: m}
	go func() { _, _ = b.Write([]byte("header and buffered body")) }()
	p := make([]byte, 64)
	n, err := c.Read(p)
	if err != nil {
		t.Fatal(err)
	}
	if m.Snapshot()["external"].(map[string]any)["upload_bytes"] != uint64(0) {
		t.Fatal("unvalidated traffic counted")
	}
	c.setScope("external")
	if m.Snapshot()["external"].(map[string]any)["upload_bytes"] != uint64(n) {
		t.Fatal("buffered bytes lost")
	}
	go func() { _, _ = io.ReadFull(b, p[:3]) }()
	if _, err := c.Write([]byte("yes")); err != nil {
		t.Fatal(err)
	}
	if m.Snapshot()["external"].(map[string]any)["download_bytes"] != uint64(3) {
		t.Fatal("downstream bytes lost")
	}
}
