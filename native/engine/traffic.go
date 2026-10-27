// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"net"
	"sync"
	"time"
)

// TrafficMeter counts only owned inputs, by validated destination scope.
type TrafficMeter struct {
	mu       sync.Mutex
	totals   [2][2]uint64
	baseline [2][2]uint64
	rates    [2][2]float64
	previous time.Time
}

func (m *TrafficMeter) Add(scope string, upload bool, count int) {
	if count <= 0 || (scope != "local" && scope != "external") {
		return
	}
	i, j := 0, 1
	if scope == "external" {
		i = 1
	}
	if upload {
		j = 0
	}
	m.mu.Lock()
	m.totals[i][j] += uint64(count)
	m.mu.Unlock()
}

func (m *TrafficMeter) Snapshot() map[string]any {
	m.mu.Lock()
	defer m.mu.Unlock()
	now := time.Now()
	if m.previous.IsZero() {
		m.previous = now
	}
	if elapsed := now.Sub(m.previous).Seconds(); elapsed >= 1 {
		for i := range 2 {
			for j := range 2 {
				m.rates[i][j] = float64(m.totals[i][j]-m.baseline[i][j]) / elapsed
			}
		}
		m.baseline, m.previous = m.totals, now
	}
	out := map[string]any{}
	for i, scope := range []string{"local", "external"} {
		out[scope] = map[string]any{"upload_bytes": m.totals[i][0], "download_bytes": m.totals[i][1],
			"upload_bps": m.rates[i][0], "download_bps": m.rates[i][1]}
	}
	return out
}

type trafficConn struct {
	net.Conn
	mu      sync.Mutex
	meter   *TrafficMeter
	scope   string
	pending int
}

func (c *trafficConn) setScope(scope string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.scope = scope
	c.meter.Add(scope, true, c.pending)
	c.pending = 0
}
func (c *trafficConn) Read(p []byte) (int, error) {
	n, err := c.Conn.Read(p)
	c.mu.Lock()
	if c.scope == "" {
		c.pending += n
	} else {
		c.meter.Add(c.scope, true, n)
	}
	c.mu.Unlock()
	return n, err
}
func (c *trafficConn) Write(p []byte) (int, error) {
	n, err := c.Conn.Write(p)
	c.mu.Lock()
	c.meter.Add(c.scope, false, n)
	c.mu.Unlock()
	return n, err
}
func (c *trafficConn) Upstream() any { return c.Conn }
func (c *trafficConn) CloseRead() error {
	if half, ok := c.Conn.(interface{ CloseRead() error }); ok {
		return half.CloseRead()
	}
	return c.Conn.SetReadDeadline(time.Now())
}
