// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"net/netip"
	"sync"
	"time"

	"github.com/metacubex/mihomo/component/resolver"
	tun "github.com/metacubex/sing-tun"
	"github.com/metacubex/sing/common/buf"
	M "github.com/metacubex/sing/common/metadata"
	N "github.com/metacubex/sing/common/network"
	D "github.com/miekg/dns"
)

const maxPhoneDNSQueries = 64
const maxPhoneDNSMessage = 4096

// The upstream TUN DNS helper starts unowned goroutines and reads a mutable
// resolver global. This handler owns a bounded set of work against one service
// snapshot, cancels it and joins it before the core can clear or replace DNS.
type phoneDNSHandler struct {
	tun.Handler
	service   resolver.Service
	ctx       context.Context
	cancel    context.CancelFunc
	mu        sync.Mutex
	closed    bool
	active    int
	tcp       map[net.Conn]struct{}
	wg        sync.WaitGroup
	closeDone chan struct{}
}

func newPhoneDNSHandler(upstream tun.Handler, service resolver.Service) (*phoneDNSHandler, error) {
	if service == nil {
		return nil, errors.New("phone DNS service is unavailable")
	}
	ctx, cancel := context.WithCancel(context.Background())
	return &phoneDNSHandler{Handler: upstream, service: service, ctx: ctx, cancel: cancel, tcp: make(map[net.Conn]struct{}), closeDone: make(chan struct{})}, nil
}

func (h *phoneDNSHandler) begin(conn net.Conn) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closed || h.active >= maxPhoneDNSQueries {
		return false
	}
	h.active++
	h.wg.Add(1)
	if conn != nil {
		h.tcp[conn] = struct{}{}
	}
	return true
}
func (h *phoneDNSHandler) end(conn net.Conn) {
	h.mu.Lock()
	h.active--
	if conn != nil {
		delete(h.tcp, conn)
	}
	h.mu.Unlock()
	h.wg.Done()
}

func (h *phoneDNSHandler) answer(payload []byte, udp bool) ([]byte, error) {
	if len(payload) > maxPhoneDNSMessage {
		return nil, errors.New("DNS message exceeds limit")
	}
	query := new(D.Msg)
	if err := query.Unpack(payload); err != nil {
		return nil, err
	}
	if len(query.Question) != 1 {
		return nil, errors.New("DNS requires one question")
	}
	ctx, cancel := context.WithTimeout(h.ctx, resolver.DefaultDnsRelayTimeout)
	defer cancel()
	response, err := h.service.ServeMsg(ctx, query)
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if err != nil || response == nil {
		response = new(D.Msg)
		response.SetRcode(query, D.RcodeServerFailure)
	}
	response.Id = query.Id
	response.Compress = true
	if udp {
		limit := 1232
		if n := resolver.RequestUDPSize(query); n < limit {
			limit = n
		}
		response.Truncate(limit)
	}
	return response.Pack()
}

func (h *phoneDNSHandler) NewPacket(ctx context.Context, key netip.AddrPort, packet *buf.Buffer, metadata M.Metadata, init func(N.PacketConn) N.PacketWriter) {
	if metadata.Destination.Port != 53 {
		h.Handler.NewPacket(ctx, key, packet, metadata, init)
		return
	}
	if packet.Len() > maxPhoneDNSMessage || !h.begin(nil) {
		packet.Release()
		return
	}
	writer := init(nil)
	go func() {
		defer h.end(nil)
		defer packet.Release()
		answer, err := h.answer(packet.Bytes(), true)
		if err != nil || h.ctx.Err() != nil {
			return
		}
		reply := buf.NewSize(len(answer))
		_, _ = reply.Write(answer)
		// gVisor's packet writer owns/releases this buffer, also on write failure.
		_ = writer.WritePacket(reply, metadata.Destination)
	}()
}

func (h *phoneDNSHandler) NewConnection(ctx context.Context, conn net.Conn, metadata M.Metadata) error {
	if metadata.Destination.Port != 53 {
		return h.Handler.NewConnection(ctx, conn, metadata)
	}
	if !h.begin(conn) {
		_ = conn.Close()
		return io.ErrClosedPipe
	}
	defer h.end(conn)
	defer conn.Close()
	var header [2]byte
	for {
		if h.ctx.Err() != nil {
			return h.ctx.Err()
		}
		_ = conn.SetReadDeadline(time.Now().Add(resolver.DefaultDnsReadTimeout))
		if _, err := io.ReadFull(conn, header[:]); err != nil {
			return err
		}
		size := int(binary.BigEndian.Uint16(header[:]))
		if size == 0 || size > maxPhoneDNSMessage {
			return errors.New("invalid DNS frame size")
		}
		payload := make([]byte, size)
		if _, err := io.ReadFull(conn, payload); err != nil {
			return err
		}
		answer, err := h.answer(payload, false)
		if err != nil {
			return err
		}
		if len(answer) > 65535 {
			return errors.New("DNS answer exceeds frame limit")
		}
		binary.BigEndian.PutUint16(header[:], uint16(len(answer)))
		_ = conn.SetWriteDeadline(time.Now().Add(resolver.DefaultDnsReadTimeout))
		if _, err = conn.Write(append(header[:], answer...)); err != nil {
			return err
		}
	}
}

func (h *phoneDNSHandler) Close() error {
	h.mu.Lock()
	if h.closed {
		h.mu.Unlock()
		<-h.closeDone
		return nil
	}
	h.closed = true
	h.cancel()
	connections := make([]net.Conn, 0, len(h.tcp))
	for c := range h.tcp {
		connections = append(connections, c)
	}
	h.mu.Unlock()
	for _, c := range connections {
		_ = c.Close()
	}
	h.wg.Wait()
	close(h.closeDone)
	return nil
}
