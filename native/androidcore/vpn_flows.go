// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"errors"
	"fmt"
	"github.com/metacubex/mihomo/component/loopback"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/sing/common"
	"net"
	"strings"
	"sync"
	"sync/atomic"
)

const maxPhoneUDPFlows = 256
const phoneUDPTokenPrefix = "PSPORTAL-PHONE/"

var phoneFlowSequence atomic.Uint64
var phoneFlowRegistry sync.Map // token -> *phoneUDPFlow; only bounded live flows
type phoneUDPFlow struct {
	owner      *phonePacketTunnel
	key, token string
	ctx        context.Context
	cancel     context.CancelFunc
	packet     *phoneOwnedPacketConn // guarded by owner.mu
	started    bool
}

func (t *phonePacketTunnel) reserveFlow(key string) *phoneUDPFlow {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.closed {
		return nil
	}
	if old := t.flows[key]; old != nil {
		return old
	}
	if len(t.flows) >= maxPhoneUDPFlows {
		return nil
	}
	ctx, cancel := context.WithCancel(t.ctx)
	flow := &phoneUDPFlow{owner: t, key: key, token: fmt.Sprintf("%s%d/%d", phoneUDPTokenPrefix, t.generation, phoneFlowSequence.Add(1)), ctx: ctx, cancel: cancel}
	t.flows[key] = flow
	phoneFlowRegistry.Store(flow.token, flow)
	return flow
}

func (f *phoneUDPFlow) release() {
	f.owner.mu.Lock()
	if f.owner.flows[f.key] == f {
		delete(f.owner.flows, f.key)
	}
	phoneFlowRegistry.Delete(f.token)
	f.cancel()
	f.owner.mu.Unlock()
}

func (f *phoneUDPFlow) releaseIfUnstarted() {
	f.owner.mu.Lock()
	if !f.started {
		if f.owner.flows[f.key] == f {
			delete(f.owner.flows, f.key)
		}
		phoneFlowRegistry.Delete(f.token)
		f.cancel()
	}
	f.owner.mu.Unlock()
}

func phoneFlowFor(m *C.Metadata) (*phoneUDPFlow, bool) {
	if m == nil || !strings.HasPrefix(m.InName, phoneUDPTokenPrefix) {
		return nil, false
	}
	value, ok := phoneFlowRegistry.Load(m.InName)
	if !ok {
		return nil, true
	}
	return value.(*phoneUDPFlow), true
}

func phoneUDPContext(ctx context.Context, m *C.Metadata) (context.Context, context.CancelFunc, error) {
	flow, phone := phoneFlowFor(m)
	if !phone {
		return ctx, func() {}, nil
	}
	if flow == nil {
		return ctx, func() {}, loopback.ErrReject
	}
	flow.owner.mu.Lock()
	if flow.owner.closed || flow.ctx.Err() != nil {
		flow.owner.mu.Unlock()
		return ctx, func() {}, loopback.ErrReject
	}
	flow.owner.dials.Add(1)
	flow.started = true
	flow.owner.mu.Unlock()
	bounded, cancel := context.WithCancel(ctx)
	stop := context.AfterFunc(flow.ctx, cancel)
	var once sync.Once
	return bounded, func() { once.Do(func() { stop(); cancel(); flow.owner.dials.Done() }) }, nil
}

func trackPhoneUDPResult(m *C.Metadata, pc C.PacketConn, err error) (C.PacketConn, error) {
	flow, phone := phoneFlowFor(m)
	if !phone {
		return pc, err
	}
	if err != nil || pc == nil {
		if pc != nil {
			_ = pc.Close()
		}
		if flow != nil {
			flow.release()
		}
		return nil, errors.Join(loopback.ErrReject, err)
	}
	if flow == nil {
		_ = pc.Close()
		return nil, loopback.ErrReject
	}
	if wrapped, ok := common.Cast[*phoneOwnedPacketConn](pc); ok {
		if wrapped.flow == flow {
			return pc, nil
		}
		_ = pc.Close()
		return nil, loopback.ErrReject
	}
	flow.owner.mu.Lock()
	if flow.owner.closed || flow.ctx.Err() != nil {
		flow.owner.mu.Unlock()
		_ = pc.Close()
		flow.release()
		return nil, loopback.ErrReject
	}
	if flow.packet != nil {
		flow.owner.mu.Unlock()
		_ = pc.Close()
		return nil, loopback.ErrReject
	}
	owned := &phoneOwnedPacketConn{PacketConn: pc, flow: flow}
	flow.packet = owned
	flow.started = true
	flow.owner.mu.Unlock()
	return owned, nil
}

type phoneOwnedPacketConn struct {
	C.PacketConn
	flow       *phoneUDPFlow
	once       sync.Once
	closeError error
}

func (p *phoneOwnedPacketConn) Upstream() any { return p.PacketConn }
func (p *phoneOwnedPacketConn) Close() error {
	p.once.Do(func() { p.closeError = p.PacketConn.Close(); p.flow.release() })
	return p.closeError
}

// Close cancels pending protocol setup, closes every owned UDP socket and waits
// for guarded dials to retire. Late results are closed, never attached to a new
// session. Per-flow nonces also isolate late upstream NAT-table cleanup.
func (t *phonePacketTunnel) Close() error {
	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		<-t.closeDone
		return nil
	}
	t.closed = true
	defer close(t.closeDone)
	t.cancel()
	flows := make([]*phoneUDPFlow, 0, len(t.flows))
	for _, flow := range t.flows {
		flows = append(flows, flow)
	}
	connections := make([]net.Conn, 0, len(t.tcp))
	for _, conn := range t.tcp {
		connections = append(connections, conn)
	}
	t.mu.Unlock()
	for _, conn := range connections {
		_ = conn.Close()
	}
	for _, flow := range flows {
		flow.owner.mu.Lock()
		pc := flow.packet
		flow.owner.mu.Unlock()
		if pc != nil {
			_ = pc.Close()
		} else {
			flow.release()
		}
	}
	t.ingress.Wait()
	t.dials.Wait()
	return nil
}
