// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import "github.com/psportal/psportal/native/engine"

func (e *Engine) SubscriptionInfo() string {
	e.mu.Lock()
	if !e.running || e.closed {
		e.mu.Unlock()
		return `{"available":false}`
	}
	ctx, url := e.ctx, e.cfg.SubscriptionURL
	e.mu.Unlock()
	return engine.SubscriptionInfoContext(ctx, url)
}
