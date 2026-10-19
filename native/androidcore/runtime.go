// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"errors"
	"github.com/metacubex/mihomo/component/loopback"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/tunnel"
	"io"
	"sync"
)

// proxyRuntime bounds adapters and upstream provider callbacks to one loaded
// profile. Late health checks cannot dial under a later session's routing/VPN.
type proxyRuntime struct {
	mu          sync.Mutex
	ctx         context.Context
	cancel      context.CancelFunc
	closed      bool
	wg          sync.WaitGroup
	connections map[io.Closer]struct{}
	ready       chan struct{}
	readyOnce   sync.Once
}

func newProxyRuntime() *proxyRuntime {
	ctx, cancel := context.WithCancel(context.Background())
	return &proxyRuntime{ctx: ctx, cancel: cancel, connections: map[io.Closer]struct{}{}, ready: make(chan struct{})}
}
func (r *proxyRuntime) begin(parent context.Context) (context.Context, func(), error) {
	r.mu.Lock()
	if r.closed {
		r.mu.Unlock()
		return nil, nil, loopback.ErrReject
	}
	r.wg.Add(1)
	r.mu.Unlock()
	ctx, cancel := context.WithCancel(parent)
	stop := context.AfterFunc(r.ctx, cancel)
	done := func() { stop(); cancel(); r.wg.Done() }
	select {
	case <-r.ready:
		return ctx, done, nil
	case <-ctx.Done():
		done()
		return nil, nil, ctx.Err()
	}
}
func (r *proxyRuntime) own(c io.Closer) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.closed {
		return false
	}
	r.connections[c] = struct{}{}
	return true
}
func (r *proxyRuntime) forget(c io.Closer) { r.mu.Lock(); delete(r.connections, c); r.mu.Unlock() }
func (r *proxyRuntime) close() {
	r.mu.Lock()
	if r.closed {
		r.mu.Unlock()
		r.wg.Wait()
		return
	}
	r.closed = true
	r.cancel()
	all := make([]io.Closer, 0, len(r.connections))
	for c := range r.connections {
		all = append(all, c)
	}
	r.mu.Unlock()
	for _, c := range all {
		_ = c.Close()
	}
	r.wg.Wait()
}

type ownedTCPConn struct {
	C.Conn
	runtime *proxyRuntime
	once    sync.Once
	err     error
}

func (c *ownedTCPConn) Close() error {
	c.once.Do(func() { c.err = c.Conn.Close(); c.runtime.forget(c) })
	return c.err
}

type ownedPacketConn struct {
	C.PacketConn
	runtime *proxyRuntime
	once    sync.Once
	err     error
}

func (c *ownedPacketConn) Close() error {
	c.once.Do(func() { c.err = c.PacketConn.Close(); c.runtime.forget(c) })
	return c.err
}
func (g *udpFailClosed) DialContext(ctx context.Context, m *C.Metadata) (C.Conn, error) {
	ctx, done, err := g.runtime.begin(ctx)
	if err != nil {
		return nil, err
	}
	defer done()
	ctx, finishPhone, err := phoneTCPContext(ctx, m)
	if err != nil {
		return nil, err
	}
	defer finishPhone()
	conn, err := g.ProxyAdapter.DialContext(ctx, m)
	if err != nil {
		return nil, err
	}
	if conn == nil {
		return nil, errors.New("Mihomo returned an empty connection")
	}
	owned := &ownedTCPConn{Conn: conn, runtime: g.runtime}
	if !g.runtime.own(owned) {
		_ = conn.Close()
		return nil, loopback.ErrReject
	}
	return owned, nil
}
func (g *udpFailClosed) ownPacket(pc C.PacketConn) (C.PacketConn, error) {
	if pc == nil {
		return nil, errors.New("Mihomo returned an empty packet connection")
	}
	var current any = pc
	for depth := 0; depth < 32; depth++ {
		if wrapped, ok := current.(*ownedPacketConn); ok && wrapped.runtime == g.runtime {
			return pc, nil
		}
		next, ok := current.(interface{ Upstream() any })
		if !ok {
			break
		}
		current = next.Upstream()
	}
	owned := &ownedPacketConn{PacketConn: pc, runtime: g.runtime}
	if !g.runtime.own(owned) {
		pc.Close()
		return nil, loopback.ErrReject
	}
	return owned, nil
}
func closeRuntime(cfg *MC.Config) {
	if cfg == nil {
		return
	}
	for _, p := range cfg.Proxies {
		if guard, ok := p.Adapter().(*udpFailClosed); ok {
			guard.runtime.close()
			return
		}
	}
}

func (c *ownedTCPConn) Upstream() any    { return c.Conn }
func (c *ownedPacketConn) Upstream() any { return c.PacketConn }
func activateRuntime(cfg *MC.Config) {
	tunnel.ResumeIngress()
	for _, p := range cfg.Proxies {
		if g, ok := p.Adapter().(*udpFailClosed); ok {
			g.runtime.readyOnce.Do(func() { close(g.runtime.ready) })
			return
		}
	}
}
