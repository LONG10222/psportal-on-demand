// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"strings"
	"sync"

	"github.com/metacubex/mihomo/component/loopback"
	C "github.com/metacubex/mihomo/constant"
)

const phoneTCPTokenPrefix = "PSPORTAL-PHONE-TCP/"

var phoneTCPRegistry sync.Map // token -> ingress owner; removed after handler returns

// TCP dials must retire when only phone routing is stopped, even while the LAN
// session keeps the shared core alive. The outer handler join owns their life.
func phoneTCPContext(ctx context.Context, m *C.Metadata) (context.Context, context.CancelFunc, error) {
	if m == nil || !strings.HasPrefix(m.InName, phoneTCPTokenPrefix) {
		return ctx, func() {}, nil
	}
	value, ok := phoneTCPRegistry.Load(m.InName)
	if !ok {
		return ctx, func() {}, loopback.ErrReject
	}
	owner := value.(*phonePacketTunnel)
	owner.mu.Lock()
	closed := owner.closed
	owner.mu.Unlock()
	if closed {
		return ctx, func() {}, loopback.ErrReject
	}
	bounded, cancel := context.WithCancel(ctx)
	stop := context.AfterFunc(owner.ctx, cancel)
	return bounded, func() { stop(); cancel() }, nil
}
