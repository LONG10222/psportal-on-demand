// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	C "github.com/metacubex/mihomo/constant"
)

func measuredNode(name string, delay int64) *node {
	return &node{proxy: &fakeNode{name: name}, healthy: true, delayMS: delay}
}

func TestFastestMeasuredStability(t *testing.T) {
	base := time.Unix(100, 0)
	a, b, d := measuredNode("A", 100), measuredNode("B", 200), measuredNode("D", 300)
	nodes := []*node{a, b, d}
	f := fastestSelection{}
	if got := f.choose(nodes, 50, base, true); got != "A" {
		t.Fatal(got)
	}
	b.delayMS = 50 // Equality with the deadband is insufficient.
	if got := f.choose(nodes, 50, base.Add(time.Minute), true); got != "A" || f.rounds != 0 {
		t.Fatal(got, f)
	}
	b.delayMS = 49
	if got := f.choose(nodes, 50, base.Add(time.Second), true); got != "A" || f.rounds != 1 {
		t.Fatal(got, f)
	}
	if got := f.choose(nodes, 50, base.Add(2*time.Second), true); got != "A" {
		t.Fatal("hold-down bypassed", got)
	}
	if got := f.choose(nodes, 50, base.Add(time.Minute), false); got != "A" {
		t.Fatal("unmeasured call switched", got)
	}
	if got := f.choose(nodes, 50, base.Add(time.Minute), true); got != "B" {
		t.Fatal(got)
	}
	// A failed incumbent fails over immediately, without waiting 30 seconds.
	b.healthy = false
	if got := f.choose(nodes, 50, base.Add(61*time.Second), false); got != "A" {
		t.Fatal(got)
	}
	a.healthy = false
	d.healthy = false
	if got := f.choose(nodes, 50, base.Add(62*time.Second), true); got != "" {
		t.Fatal("failed nodes selected", got)
	}
}

func TestFastestChallengerResetAndZeroMeasurement(t *testing.T) {
	base := time.Unix(100, 0)
	a, b, d := measuredNode("A", 100), measuredNode("B", 200), measuredNode("D", 300)
	nodes := []*node{a, b, d}
	f := fastestSelection{}
	f.choose(nodes, 10, base, true)
	b.delayMS = 20
	f.choose(nodes, 10, base.Add(time.Minute), true)
	d.delayMS = 0
	if got := f.choose(nodes, 10, base.Add(61*time.Second), true); got != "A" || f.rounds != 1 || f.challenger != "D" {
		t.Fatal(got, f)
	}
	if got := f.choose(nodes, 10, base.Add(62*time.Second), true); got != "D" {
		t.Fatal(got)
	}
	if got := nodeDelay(d); got != int64(0) {
		t.Fatal("real zero measurement hidden", got)
	}
	d.healthy = false
	if nodeDelay(d) != nil {
		t.Fatal("failed measurement exposed")
	}
}

func TestLiveSelectionDoesNotCountUnmeasuredRounds(t *testing.T) {
	c := newEmbeddedCore(validConfig())
	defer c.Close()
	a, b := measuredNode("Hong Kong", 100), measuredNode("Japan", 200)
	c.mu.Lock()
	c.nodes = []*node{a, b}
	c.updateHealthLocked(true)
	c.mu.Unlock()
	if err := c.changeSelection("fastest", "", nil, false); err != nil {
		t.Fatal(err)
	}
	c.mu.Lock()
	b.delayMS = 0
	c.fastest.switchedAt = time.Now().Add(-time.Minute)
	c.chooseLocked(true)
	c.mu.Unlock()
	for i := 0; i < 3; i++ {
		if err := c.changeSelection("fastest", "", nil, false); err != nil {
			t.Fatal(err)
		}
	}
	if got := c.Status()["selected_node"]; got != "Hong Kong" {
		t.Fatal("select counted as probe round", got)
	}
	c.mu.Lock()
	c.chooseLocked(true)
	c.mu.Unlock()
	if got := c.Status()["selected_node"]; got != "Japan" {
		t.Fatal(got)
	}
	if err := c.changeSelection("auto", "", nil, false); err != nil {
		t.Fatal(err)
	}
	if got := c.Status()["selected_node"]; got != "Hong Kong" {
		t.Fatal("legacy HK priority changed", got)
	}
	if err := c.changeSelection("fixed", "missing", nil, false); err == nil {
		t.Fatal("unknown node accepted")
	}
	if err := c.changeSelection("fixed", "Japan", nil, false); err != nil {
		t.Fatal(err)
	}
	c.mu.Lock()
	b.healthy = false
	c.updateHealthLocked(false)
	c.mu.Unlock()
	if got := c.Status(); got["core_state"] != "error" || got["selected_node"] != "Japan" {
		t.Fatal(got)
	}
	c.mu.Lock()
	candidates := c.candidatesLocked()
	c.mu.Unlock()
	if len(candidates) != 0 {
		t.Fatal("fixed mode fell back")
	}
}

type fixtureProxyConn struct {
	C.Conn
	connection net.Conn
}

func (c fixtureProxyConn) Read(p []byte) (int, error)        { return c.connection.Read(p) }
func (c fixtureProxyConn) Write(p []byte) (int, error)       { return c.connection.Write(p) }
func (c fixtureProxyConn) Close() error                      { return c.connection.Close() }
func (c fixtureProxyConn) LocalAddr() net.Addr               { return c.connection.LocalAddr() }
func (c fixtureProxyConn) RemoteAddr() net.Addr              { return c.connection.RemoteAddr() }
func (c fixtureProxyConn) SetDeadline(t time.Time) error     { return c.connection.SetDeadline(t) }
func (c fixtureProxyConn) SetReadDeadline(t time.Time) error { return c.connection.SetReadDeadline(t) }
func (c fixtureProxyConn) SetWriteDeadline(t time.Time) error {
	return c.connection.SetWriteDeadline(t)
}

func healthFixtureNode(name string, count *atomic.Int32) *node {
	n := &fakeNode{name: name}
	n.dial = func(ctx context.Context, _ *C.Metadata) (C.Conn, error) {
		count.Add(1)
		client, server := net.Pipe()
		go func() {
			defer server.Close()
			_ = server.SetDeadline(time.Now().Add(time.Second))
			if _, err := readHeader(bufio.NewReader(server)); err == nil {
				_, _ = io.WriteString(server, "HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
			}
		}()
		return fixtureProxyConn{connection: client}, nil
	}
	return &node{proxy: n}
}

func TestPrepareReusesInitialHealthAndKeepsFailedPool(t *testing.T) {
	for _, healthy := range []bool{true, false} {
		t.Run(map[bool]string{true: "healthy", false: "failed"}[healthy], func(t *testing.T) {
			cfg := validConfig()
			cfg.HealthURL = "http://8.8.8.8/health"
			c := newEmbeddedCore(cfg)
			defer c.Close()
			var attempts, loads atomic.Int32
			n := healthFixtureNode("Fixture", &attempts)
			if !healthy {
				n.proxy.(*fakeNode).dial = func(context.Context, *C.Metadata) (C.Conn, error) { attempts.Add(1); return nil, errors.New("offline") }
			}
			c.loader = func(context.Context, Config) ([]*node, error) { loads.Add(1); return []*node{n}, nil }
			err := c.prepare()
			if (err == nil) != healthy {
				t.Fatal(err)
			}
			if attempts.Load() != 1 || loads.Load() != 1 {
				t.Fatal("initial prepare duplicated probes", attempts.Load(), loads.Load())
			}
			if len(c.Status()["nodes"].([]map[string]any)) != 1 {
				t.Fatal("failed pool disappeared")
			}
			if err := c.changeSelection("fixed", "Fixture", nil, false); err != nil {
				t.Fatal(err)
			}
			_ = c.prepare()
			if attempts.Load() != 2 || loads.Load() != 1 {
				t.Fatal("retry must reprobe existing pool", attempts.Load(), loads.Load())
			}
		})
	}
}

func TestCancelledHealthBatchKeepsMeasurements(t *testing.T) {
	cfg := validConfig()
	cfg.HealthURL = "http://8.8.8.8/health"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	a := measuredNode("A", 100)
	b := &node{proxy: &fakeNode{name: "B", dial: func(ctx context.Context, _ *C.Metadata) (C.Conn, error) { <-ctx.Done(); return nil, ctx.Err() }}, healthy: true, delayMS: 200}
	c.mu.Lock()
	c.nodes = []*node{a, b}
	c.mu.Unlock()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	time.AfterFunc(20*time.Millisecond, cancel)
	c.checkHealth(ctx, []*node{a, b})
	c.mu.Lock()
	defer c.mu.Unlock()
	if !a.healthy || a.delayMS != 100 || !b.healthy || b.delayMS != 200 {
		t.Fatal("cancelled partial batch altered measurements")
	}
}

func TestPrepareStopAndStatusConcurrent(t *testing.T) {
	cfg := validConfig()
	cfg.ListenHost = "127.0.0.1"
	cfg.ListenPort = 0
	cfg.AllowedClients = []string{"127.0.0.1"}
	cfg.HealthURL = "http://8.8.8.8/health"
	c := newEmbeddedCore(cfg)
	entered := make(chan struct{})
	var once sync.Once
	n := &fakeNode{name: "blocked", dial: func(ctx context.Context, _ *C.Metadata) (C.Conn, error) {
		once.Do(func() { close(entered) })
		<-ctx.Done()
		return nil, ctx.Err()
	}}
	c.mu.Lock()
	c.nodes = []*node{{proxy: n, healthy: true, delayMS: 10}}
	c.mu.Unlock()
	p := NewProxy(cfg, c)
	if err := p.Start(); err != nil {
		t.Fatal(err)
	}
	e := &Engine{cfg: cfg, core: c, proxy: p, running: true}
	defer e.Stop()
	prepared := make(chan error, 1)
	go func() { prepared <- e.Prepare() }()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("probe never entered")
	}
	var status map[string]any
	if err := json.Unmarshal([]byte(e.Status()), &status); err != nil || status["state"] != "preparing" {
		t.Fatal(status, err)
	}
	selected := make(chan error, 1)
	go func() { selected <- e.SelectNode("fixed", "blocked") }()
	stopped := make(chan struct{})
	go func() { e.Stop(); close(stopped) }()
	select {
	case <-stopped:
	case <-time.After(time.Second):
		t.Fatal("Stop blocked on network probe")
	}
	if err := <-prepared; err == nil {
		t.Fatal("cancelled prepare succeeded")
	}
	if err := <-selected; err == nil {
		t.Fatal("selection succeeded after Stop")
	}
	if n.closed.Load() != 1 {
		t.Fatal("node not closed exactly once", n.closed.Load())
	}
	if err := json.Unmarshal([]byte(e.Status()), &status); err != nil || status["state"] != "stopped" || status["running"] != false {
		t.Fatal(status, err)
	}
}

func TestFastestConfigThreshold(t *testing.T) {
	cfg := validConfig()
	cfg.SelectionMode = "fastest"
	for _, threshold := range []int{0, 50, 60000} {
		cfg.SwitchThresholdMS = threshold
		if err := cfg.Validate(); err != nil {
			t.Fatal(err)
		}
	}
	for _, threshold := range []int{-1, 60001} {
		cfg.SwitchThresholdMS = threshold
		if err := cfg.Validate(); err == nil {
			t.Fatal("invalid threshold accepted")
		}
	}
}

func TestLiveFixedSwitchPreservesOpenStream(t *testing.T) {
	cfg := validConfig()
	cfg.HealthURL = "http://8.8.8.8/health"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	var aDials, bDials atomic.Int32
	echo := func(counter *atomic.Int32) func(context.Context, *C.Metadata) (C.Conn, error) {
		return func(_ context.Context, m *C.Metadata) (C.Conn, error) {
			counter.Add(1)
			client, server := net.Pipe()
			go func() {
				defer server.Close()
				if m.DstPort == 80 {
					if _, err := readHeader(bufio.NewReader(server)); err == nil {
						_, _ = io.WriteString(server, "HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
					}
				} else {
					_, _ = io.Copy(server, server)
				}
			}()
			return fixtureProxyConn{connection: client}, nil
		}
	}
	a := &fakeNode{name: "Hong Kong", dial: echo(&aDials)}
	b := &fakeNode{name: "Japan", dial: echo(&bDials)}
	c.mu.Lock()
	c.nodes = []*node{{proxy: a, healthy: true, delayMS: 100}, {proxy: b, healthy: true, delayMS: 10}}
	c.updateHealthLocked(true)
	c.mu.Unlock()
	if _, err := c.Acquire(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer c.Release()
	first, err := c.DialExternal(context.Background(), "8.8.8.8", 443)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	if err := c.selectNode("fixed", "Japan", nil); err != nil {
		t.Fatal(err)
	}
	second, err := c.DialExternal(context.Background(), "8.8.8.8", 443)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	for _, conn := range []net.Conn{first, second} {
		_ = conn.SetDeadline(time.Now().Add(time.Second))
		if _, err := conn.Write([]byte("ping")); err != nil {
			t.Fatal(err)
		}
		response := make([]byte, 4)
		if _, err := io.ReadFull(conn, response); err != nil || string(response) != "ping" {
			t.Fatal("live switch interrupted stream", err, string(response))
		}
	}
	if aDials.Load() != 1 || bDials.Load() != 2 || a.closed.Load() != 0 || b.closed.Load() != 0 {
		t.Fatal("switch rebuilt or closed adapters")
	}
}

func TestIdleAndStopDoNotWakeHealthProbes(t *testing.T) {
	cfg := validConfig()
	cfg.HealthInterval = 1
	c := newEmbeddedCore(cfg)
	var loads atomic.Int32
	c.loader = func(context.Context, Config) ([]*node, error) {
		loads.Add(1)
		return nil, errors.New("unexpected background load")
	}
	time.Sleep(1100 * time.Millisecond)
	c.Close()
	if loads.Load() != 0 {
		t.Fatal("maintenance woke idle subscription")
	}
	if err := c.prepare(); !errors.Is(err, errStopped) {
		t.Fatal(err)
	}
	if loads.Load() != 0 {
		t.Fatal("stopped prepare loaded subscription")
	}
}

func TestMissingFixedNodeRetainsPoolForExplicitRecovery(t *testing.T) {
	cfg := validConfig()
	cfg.SelectionMode = "fixed"
	cfg.PreferredNode = "Removed"
	cfg.HealthURL = "http://8.8.8.8/health"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	var attempts atomic.Int32
	n := healthFixtureNode("Available", &attempts)
	c.loader = func(context.Context, Config) ([]*node, error) { return []*node{n}, nil }
	if err := c.prepare(); !errors.Is(err, errFixedMissing) {
		t.Fatal(err)
	}
	status := c.Status()
	if status["error"] != errFixedMissing.Error() || len(status["nodes"].([]map[string]any)) != 1 {
		t.Fatal(status)
	}
	c.mu.Lock()
	candidates := c.candidatesLocked()
	c.mu.Unlock()
	if len(candidates) != 0 {
		t.Fatal("missing fixed node fell back")
	}
	if err := c.changeSelection("fixed", "Available", nil, false); err != nil {
		t.Fatal(err)
	}
	if status := c.Status(); status["error"] != "" || status["selected_node"] != "Available" || status["core_state"] != "running" {
		t.Fatal(status)
	}
	if attempts.Load() != 1 {
		t.Fatal("explicit selection performed an unrequested probe")
	}
}

func TestHealthDeadlineRetainsCompletedMeasurements(t *testing.T) {
	cfg := validConfig()
	cfg.HealthURL = "http://8.8.8.8/health"
	cfg.HealthTimeout = 5000
	c := newEmbeddedCore(cfg)
	defer c.Close()
	var attempts atomic.Int32
	healthy := healthFixtureNode("Healthy", &attempts)
	slow := &node{proxy: &fakeNode{name: "Slow", dial: func(ctx context.Context, _ *C.Metadata) (C.Conn, error) { <-ctx.Done(); return nil, ctx.Err() }}, healthy: true, delayMS: 200}
	c.mu.Lock()
	c.nodes = []*node{healthy, slow}
	c.mode = "fastest"
	c.fastest = fastestSelection{current: "Slow", challenger: "Healthy", rounds: 1, switchedAt: time.Now().Add(-time.Minute)}
	c.mu.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	c.checkHealth(ctx, []*node{healthy, slow})
	c.mu.Lock()
	defer c.mu.Unlock()
	if !healthy.healthy || !slow.healthy || slow.delayMS != 200 {
		t.Fatal("deadline discarded completed or rewrote unfinished measurements")
	}
	if c.fastest.current != "Slow" || c.fastest.rounds != 0 {
		t.Fatal("partial deadline counted as stability round", c.fastest)
	}
}

func TestFixedStartupDoesNotProbeUnrelatedSlowNodes(t *testing.T) {
	cfg := validConfig()
	cfg.SelectionMode = "fixed"
	cfg.PreferredNode = "Chosen"
	cfg.HealthURL = "http://8.8.8.8/health"
	cfg.WakeupTimeout = 1
	cfg.HealthTimeout = 5000
	c := newEmbeddedCore(cfg)
	defer c.Close()
	var fast, slow atomic.Int32
	nodes := make([]*node, 0, 21)
	for i := 0; i < 20; i++ {
		nodes = append(nodes, &node{proxy: &fakeNode{name: fmt.Sprintf("Slow %d", i), dial: func(ctx context.Context, _ *C.Metadata) (C.Conn, error) {
			slow.Add(1)
			<-ctx.Done()
			return nil, ctx.Err()
		}}})
	}
	nodes = append(nodes, healthFixtureNode("Chosen", &fast))
	c.loader = func(context.Context, Config) ([]*node, error) { return nodes, nil }
	done := make(chan error, 1)
	go func() { done <- c.prepare() }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("fixed startup waited for unrelated nodes")
	}
	if fast.Load() != 1 || slow.Load() != 0 {
		t.Fatal("unrelated startup probes", fast.Load(), slow.Load())
	}
	if status := c.Status(); len(status["nodes"].([]map[string]any)) != 21 || status["selected_node"] != "Chosen" || status["core_state"] != "running" {
		t.Fatal(status)
	}
}

func TestMeasuredSelectionTestsUntestedTargetBeforeSwitch(t *testing.T) {
	cfg := validConfig()
	cfg.SelectionMode = "fixed"
	cfg.PreferredNode = "Old"
	cfg.HealthURL = "http://8.8.8.8/health"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	var probes atomic.Int32
	target := healthFixtureNode("New", &probes)
	old := measuredNode("Old", 100)
	c.mu.Lock()
	c.nodes = []*node{old, target}
	c.updateHealthLocked(true)
	c.mu.Unlock()
	if err := c.selectNode("fixed", "New", nil); err != nil {
		t.Fatal(err)
	}
	if status := c.Status(); status["selected_node"] != "New" || status["error"] != "" || probes.Load() != 1 {
		t.Fatal(status, probes.Load())
	}
	if err := c.selectNode("fixed", "Old", nil); !errors.Is(err, errNoHealthy) {
		t.Fatal("offline target must fail staged switch", err)
	}
	if status := c.Status(); status["selected_node"] != "New" || status["selection_mode"] != "fixed" {
		t.Fatal("failed switch changed policy", status)
	}
}

func TestMeasuredFastestSelectionProbesFullPool(t *testing.T) {
	cfg := validConfig()
	cfg.SelectionMode = "fixed"
	cfg.PreferredNode = "Old"
	cfg.HealthURL = "http://8.8.8.8/health"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	var first, second atomic.Int32
	a, b := healthFixtureNode("A", &first), healthFixtureNode("B", &second)
	c.mu.Lock()
	c.nodes = []*node{a, b}
	c.mu.Unlock()
	if err := c.selectNode("fastest", "", nil); err != nil {
		t.Fatal(err)
	}
	if first.Load() != 1 || second.Load() != 1 {
		t.Fatal("fastest did not measure full pool")
	}
	if status := c.Status(); status["selection_mode"] != "fastest" || status["selected_node"] == "" || status["error"] != "" {
		t.Fatal(status)
	}
}

func TestFastestSelectionCommandCountsOneMeasuredRound(t *testing.T) {
	cfg := validConfig()
	cfg.SelectionMode = "fastest"
	cfg.SwitchThresholdMS = 0
	cfg.HealthURL = "http://8.8.8.8/health"
	c := newEmbeddedCore(cfg)
	defer c.Close()
	var aCount, bCount atomic.Int32
	a, b := healthFixtureNode("Old", &aCount), healthFixtureNode("New", &bCount)
	original := a.proxy.(*fakeNode).dial
	a.proxy.(*fakeNode).dial = func(ctx context.Context, m *C.Metadata) (C.Conn, error) {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(30 * time.Millisecond):
			return original(ctx, m)
		}
	}
	a.healthy, a.delayMS = true, 30
	b.healthy, b.delayMS = true, 0
	c.mu.Lock()
	c.nodes = []*node{a, b}
	c.selected = "Old"
	c.fastest = fastestSelection{current: "Old", challenger: "New", rounds: 1, switchedAt: time.Now().Add(-time.Minute)}
	c.mu.Unlock()
	wider := 1000
	if err := c.selectNode("fastest", "", &wider); err != nil {
		t.Fatal(err)
	}
	if status := c.Status(); status["selected_node"] != "Old" {
		t.Fatal("probe applied old threshold before staged threshold", status)
	}
	zero := 0
	if err := c.selectNode("fastest", "", &zero); err != nil {
		t.Fatal(err)
	}
	if status := c.Status(); status["selected_node"] != "Old" {
		t.Fatal("one measurement counted twice", status)
	}
	if err := c.selectNode("fastest", "", &zero); err != nil {
		t.Fatal(err)
	}
	if status := c.Status(); status["selected_node"] != "New" {
		t.Fatal("two measured rounds did not switch", status)
	}
}
