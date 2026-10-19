// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"errors"
	"github.com/metacubex/mihomo/adapter"
	"github.com/metacubex/mihomo/component/loopback"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
)

// Mihomo's rule matcher skips adapters reporting !SupportUDP and may then fall
// through to DIRECT. This wrapper makes an explicitly matched unsupported route
// a terminal error. The underlying UDP capability remains checked at dial time.
// Mutate each existing *adapter.Proxy before ApplyConfig starts workers: group
// and provider references must continue pointing at that very same wrapper.
type udpFailClosed struct {
	C.ProxyAdapter
	runtime *proxyRuntime
}

func (g *udpFailClosed) SupportUDP() bool { return true }
func (g *udpFailClosed) ListenPacketContext(ctx context.Context, m *C.Metadata) (C.PacketConn, error) {
	if !g.ProxyAdapter.SupportUDP() {
		return trackPhoneUDPResult(m, nil, errors.Join(errors.New("selected proxy does not support UDP; direct fallback is disabled"), loopback.ErrReject))
	}
	ctx, done, err := g.runtime.begin(ctx)
	if err != nil {
		return trackPhoneUDPResult(m, nil, err)
	}
	defer done()
	ctx, cancel, err := phoneUDPContext(ctx, m)
	if err != nil {
		return trackPhoneUDPResult(m, nil, err)
	}
	defer cancel()
	pc, err := g.ProxyAdapter.ListenPacketContext(ctx, m)
	if err == nil {
		pc, err = g.ownPacket(pc)
	}
	return trackPhoneUDPResult(m, pc, err)
}

func installUDPGuards(cfg *MC.Config) error {
	runtime := newProxyRuntime()
	for _, proxy := range cfg.Proxies {
		p, ok := proxy.(*adapter.Proxy)
		if !ok {
			return errors.New("unexpected Mihomo proxy wrapper")
		}
		if _, ok := p.ProxyAdapter.(*udpFailClosed); !ok {
			p.ProxyAdapter = &udpFailClosed{ProxyAdapter: p.ProxyAdapter, runtime: runtime}
		}
	}
	return nil
}
func originalAdapter(proxy C.Proxy) C.ProxyAdapter {
	a := proxy.Adapter()
	if guard, ok := a.(*udpFailClosed); ok {
		return guard.ProxyAdapter
	}
	return a
}
