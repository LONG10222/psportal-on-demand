// SPDX-License-Identifier: GPL-3.0-only
//go:build android

package androidcore

import (
	"context"
	"errors"
	"io"
	"net/netip"
	"sync"
	"time"

	"github.com/metacubex/mihomo/adapter/inbound"
	"github.com/metacubex/mihomo/component/resolver"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/listener/sing"
	"github.com/metacubex/mihomo/listener/sing_tun"
	"github.com/metacubex/mihomo/log"
	"github.com/metacubex/mihomo/tunnel"
	tun "github.com/metacubex/sing-tun"
	"golang.org/x/sys/unix"
)

type androidPhoneTunnel struct {
	once    sync.Once
	cancel  context.CancelFunc
	device  tun.Tun
	stack   tun.Stack
	packets io.Closer
	dns     io.Closer
}

func (t *androidPhoneTunnel) Close() error {
	t.once.Do(func() {
		t.cancel()
		if t.dns != nil {
			_ = t.dns.Close()
		}
		if t.packets != nil {
			_ = t.packets.Close()
		}
		if t.stack != nil {
			_ = t.stack.Close()
		}
		if t.device != nil {
			_ = t.device.Close()
		}
	})
	return nil
}

// StartPhoneVPN duplicates a descriptor still owned by Java. Native closes only
// its duplicate; Java closes its original after native stop, including failures.
// Host builds cannot execute this function, so tests never create host VPNs.
func (e *Engine) StartPhoneVPN(fd int, protector SocketProtector) error {
	if fd <= 0 || protector == nil {
		return errors.New("VPN descriptor and protector required")
	}
	if !e.cfg.PhoneVPN {
		return errors.New("phone VPN was not requested for this session")
	}
	if err := e.Prepare(); err != nil {
		return err
	}
	e.lifeMu.Lock()
	defer e.lifeMu.Unlock()
	e.mu.Lock()
	ready := e.current != nil && e.ctx.Err() == nil
	e.mu.Unlock()
	if !ready {
		return errors.New("core is not running")
	}
	phoneSession.Lock()
	busy := phoneSession.closer != nil
	phoneSession.Unlock()
	if busy {
		return errors.New("phone VPN is already running")
	}
	duplicate, err := unix.FcntlInt(uintptr(fd), unix.F_DUPFD_CLOEXEC, 3)
	if err != nil {
		return errors.New("VPN descriptor duplication failed")
	}
	unix.CloseOnExec(duplicate)
	ctx, cancel := context.WithCancel(e.ctx)
	owned := &androidPhoneTunnel{cancel: cancel}
	success := false
	defer func() {
		if !success {
			_ = owned.Close()
			blockPhoneSocketProtection(e)
		}
	}()
	// The external-descriptor branch of pinned sing-tun takes ownership immediately
	// and never configures host routes, interfaces, firewall or DNS settings.
	options := tun.Options{Name: "psportal-phone", FileDescriptor: duplicate, MTU: 1500, EXP_DisableDNSHijack: true,
		Inet4Address: []netip.Prefix{netip.MustParsePrefix("198.18.0.1/30")},
		Inet6Address: []netip.Prefix{netip.MustParsePrefix("fdfe:dcba:9876::1/126")}}
	owned.device, err = tun.New(options)
	if err != nil {
		_ = unix.Close(duplicate)
		return errors.New("VPN packet interface failed")
	}
	packetTunnel := newPhonePacketTunnel(tunnel.Tunnel)
	owned.packets = packetTunnel.(io.Closer)
	handler, err := sing.NewListenerHandler(sing.ListenerConfig{Tunnel: packetTunnel, Type: C.TUN,
		Additions: []inbound.Addition{inbound.WithInName("PSPORTAL-PHONE")}})
	if err != nil {
		return errors.New("VPN packet handler failed")
	}
	dnsHandler := &sing_tun.ListenerHandler{ListenerHandler: handler, Inet4Address: options.Inet4Address, Inet6Address: options.Inet6Address,
		DnsAddrPorts: []netip.AddrPort{netip.MustParseAddrPort("0.0.0.0:53"), netip.MustParseAddrPort("[::]:53")}, DisableICMPForwarding: true}
	ownedDNS, err := newPhoneDNSHandler(dnsHandler, resolver.DefaultService)
	if err != nil {
		return err
	}
	owned.dns = ownedDNS
	requirePhoneSocketProtection(e, protector)
	owned.stack, err = tun.NewStack("gvisor", tun.StackOptions{Context: ctx, Tun: owned.device, TunOptions: options, Handler: ownedDNS, Logger: log.SingLogger, UDPTimeout: time.Minute, ICMPTimeout: 10 * time.Second})
	if err != nil {
		return errors.New("VPN packet stack unavailable")
	}
	if err = owned.stack.Start(); err != nil {
		return errors.New("VPN packet stack failed")
	}
	phoneSession.Lock()
	phoneSession.owner, phoneSession.closer = e, owned
	phoneSession.Unlock()
	success = true
	return nil
}
