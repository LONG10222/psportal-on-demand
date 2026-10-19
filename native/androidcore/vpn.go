// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"errors"
	"io"
	"sync"
	"syscall"

	"github.com/metacubex/mihomo/component/dialer"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
)

// SocketProtector is implemented only by the consented Android VpnService.
// A false result prevents the socket from connecting; it must never be ignored.
type SocketProtector interface{ Protect(fd int) bool }

var socketPolicyOnce sync.Once
var socketPolicy struct {
	sync.RWMutex
	owner    *Engine
	previous dialer.SocketControl
}
var vpnProtection struct {
	sync.RWMutex
	owner     *Engine
	protector SocketProtector
	required  bool
}
var phoneSession struct {
	sync.Mutex
	owner  *Engine
	closer io.Closer
}

func initializeSocketPolicy() {
	socketPolicyOnce.Do(func() {
		socketPolicy.previous = dialer.DefaultSocketHook
		dialer.DefaultSocketHook = func(network, address string, raw syscall.RawConn) error {
			socketPolicy.RLock()
			active, previous := socketPolicy.owner != nil, socketPolicy.previous
			socketPolicy.RUnlock()
			if !active {
				if previous != nil {
					return previous(network, address, raw)
				}
				return nil
			}
			if err := guardSocketDestination(network, address); err != nil {
				return err
			}
			return protectVPNRawConn(raw)
		}
	})
}

func activateSocketPolicy(owner *Engine) {
	initializeSocketPolicy()
	socketPolicy.Lock()
	socketPolicy.owner = owner
	socketPolicy.Unlock()
}

func retireSocketPolicy(owner *Engine) {
	socketPolicy.Lock()
	if socketPolicy.owner == owner {
		socketPolicy.owner = nil
	}
	socketPolicy.Unlock()
}

func protectVPNRawConn(raw syscall.RawConn) error {
	vpnProtection.RLock()
	defer vpnProtection.RUnlock()
	if vpnProtection.protector == nil {
		if vpnProtection.required {
			return errors.New("VPN socket protection is stopping")
		}
		return nil
	}
	protected := false
	if err := raw.Control(func(fd uintptr) { protected = vpnProtection.protector.Protect(int(fd)) }); err != nil {
		return errors.New("VPN socket control failed")
	}
	if !protected {
		return errors.New("VPN socket protection failed")
	}
	return nil
}

func requirePhoneSocketProtection(owner *Engine, protector SocketProtector) {
	vpnProtection.Lock()
	vpnProtection.owner, vpnProtection.protector, vpnProtection.required = owner, protector, true
	vpnProtection.Unlock()
}

func blockPhoneSocketProtection(owner *Engine) {
	vpnProtection.Lock()
	if vpnProtection.owner == owner {
		vpnProtection.protector = nil
	}
	vpnProtection.Unlock()
}

// DNS is handled inside Mihomo, with no DNS listener opened on the LAN. Numeric
// HTTPS endpoints require no DNS bootstrap and use the same protected sockets.
// This intentionally does not import arbitrary subscription DNS or OS Private DNS.
func configureVPNDNS(raw *MC.RawConfig) {
	servers := []string{"https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"}
	raw.DNS = MC.RawDNS{Enable: true, IPv6: true, EnhancedMode: C.DNSMapping, NameServer: servers,
		DefaultNameserver: append([]string(nil), servers...), CacheAlgorithm: "lru", CacheMaxSize: 1024}
}

func (e *Engine) phoneVPNActive() bool {
	phoneSession.Lock()
	defer phoneSession.Unlock()
	return phoneSession.owner == e && phoneSession.closer != nil
}

// StopPhoneVPN releases only the optional phone tunnel. The LAN proxy keeps its
// own lifecycle. Engine.Stop calls stopPhoneVPNLocked while holding lifeMu.
func (e *Engine) StopPhoneVPN() {
	e.lifeMu.Lock()
	defer e.lifeMu.Unlock()
	e.stopPhoneVPNLocked()
}

func (e *Engine) stopPhoneVPNLocked() {
	phoneSession.Lock()
	if phoneSession.owner != e {
		phoneSession.Unlock()
		return
	}
	closer := phoneSession.closer
	phoneSession.owner, phoneSession.closer = nil, nil
	phoneSession.Unlock()
	// Keep protection installed until the packet stack and all owned sockets close.
	if closer != nil {
		_ = closer.Close()
	}
	blockPhoneSocketProtection(e)
}

// ReleasePhoneVPNProtection runs after Java closes its original descriptor.
// Upstream sockets remain blocked until both descriptor owners have released it.
func ReleasePhoneVPNProtection() {
	phoneSession.Lock()
	defer phoneSession.Unlock()
	if phoneSession.closer != nil {
		return
	}
	vpnProtection.Lock()
	vpnProtection.owner, vpnProtection.protector, vpnProtection.required = nil, nil, false
	vpnProtection.Unlock()
}
