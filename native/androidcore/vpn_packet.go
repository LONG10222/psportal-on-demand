// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"fmt"
	N "github.com/metacubex/mihomo/common/net"
	C "github.com/metacubex/mihomo/constant"
	"github.com/psportal/psportal/native/engine"
	"net"
	"sync"
	"sync/atomic"
)

const maxPhoneTCPFlows = 256

var phoneTunnelGeneration atomic.Uint64

type phonePacketTunnel struct {
	C.Tunnel
	generation uint64
	mu         sync.Mutex
	closed     bool
	flows      map[string]*phoneUDPFlow
	ctx        context.Context
	cancel     context.CancelFunc
	dials      sync.WaitGroup
	ingress    sync.WaitGroup
	tcp        map[string]net.Conn
	closeDone  chan struct{}
}

func newPhonePacketTunnel(upstream C.Tunnel) C.Tunnel {
	ctx, cancel := context.WithCancel(context.Background())
	return &phonePacketTunnel{Tunnel: upstream, generation: phoneTunnelGeneration.Add(1), flows: make(map[string]*phoneUDPFlow), ctx: ctx, cancel: cancel, closeDone: make(chan struct{}), tcp: make(map[string]net.Conn)}
}

// TUN ingress supplies numeric destinations. Keep the private-network boundary
// on packets as well as connected sockets (UDP sendto bypasses socket Control).
func phoneDestinationAllowed(metadata *C.Metadata) bool {
	return metadata != nil && metadata.DstIP.IsValid() && engine.Destination(metadata.DstIP.Unmap().String()) == "external"
}

func (t *phonePacketTunnel) HandleTCPConn(conn net.Conn, metadata *C.Metadata) {
	if !phoneDestinationAllowed(metadata) {
		_ = conn.Close()
		return
	}
	t.mu.Lock()
	if t.closed || len(t.tcp) >= maxPhoneTCPFlows {
		t.mu.Unlock()
		_ = conn.Close()
		return
	}
	token := fmt.Sprintf("%s%d/%d", phoneTCPTokenPrefix, t.generation, phoneFlowSequence.Add(1))
	t.tcp[token] = conn
	t.ingress.Add(1)
	phoneTCPRegistry.Store(token, t)
	t.mu.Unlock()
	defer func() {
		_ = conn.Close()
		t.mu.Lock()
		delete(t.tcp, token)
		phoneTCPRegistry.Delete(token)
		t.mu.Unlock()
		t.ingress.Done()
	}()
	metadata = metadata.Clone()
	metadata.InName = token
	t.Tunnel.HandleTCPConn(conn, metadata)
}

// The pinned tunnel's NAT key contains only the source socket. Without this
// boundary, a later destination can reuse an earlier DIRECT socket instead of
// matching its own proxy rule. Key by session and full destination as well.
func (t *phonePacketTunnel) HandleUDPPacket(packet C.UDPPacket, metadata *C.Metadata) {
	if packet == nil {
		return
	}
	if !phoneDestinationAllowed(metadata) || packet.LocalAddr() == nil {
		packet.Drop()
		return
	}
	key := fmt.Sprintf("%s/%s/%d/%q", packet.LocalAddr().String(), metadata.DstIP, metadata.DstPort, metadata.Host)
	flow := t.reserveFlow(key)
	if flow == nil {
		packet.Drop()
		return
	}
	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		packet.Drop()
		flow.release()
		return
	}
	t.ingress.Add(1)
	t.mu.Unlock()
	metadata = metadata.Clone()
	metadata.InName = flow.token
	t.Tunnel.HandleUDPPacket(&phoneDestinationPacket{UDPPacket: packet, address: N.NewCustomAddr("psportal-phone-udp", flow.token, packet.LocalAddr()), flow: flow}, metadata)
}

type phoneDestinationPacket struct {
	C.UDPPacket
	address net.Addr
	flow    *phoneUDPFlow
	once    sync.Once
}

func (p *phoneDestinationPacket) LocalAddr() net.Addr { return p.address }
func (p *phoneDestinationPacket) Drop() {
	p.once.Do(func() {
		p.UDPPacket.Drop()
		// Queue/metadata rejection may happen before any dial. Every admitted
		// packet remains joined through matching and send or terminal rejection.
		p.flow.releaseIfUnstarted()
		p.flow.owner.ingress.Done()
	})
}
func (p *phoneDestinationPacket) InAddr() net.Addr {
	if source, ok := p.UDPPacket.(C.UDPPacketInAddr); ok {
		return source.InAddr()
	}
	return nil
}
