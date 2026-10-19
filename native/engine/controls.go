// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"encoding/json"
	"time"
)

// NodeCommand controls only this Engine's adapter pool. No controller listener
// or third-party process is used. Explicit preparation may wake our idle pool.
func (e *Engine) NodeCommand(raw string) string {
	fail := func(code string) string {
		b, _ := json.Marshal(map[string]any{"ok": false, "code": code})
		return string(b)
	}
	var command struct {
		Action string `json:"action"`
		Name   string `json:"name"`
	}
	if len(raw) > 2048 || json.Unmarshal([]byte(raw), &command) != nil {
		return fail("invalid")
	}
	if command.Action != "prepare" && command.Action != "probe" && command.Action != "select" && command.Action != "fastest" {
		return fail("invalid")
	}
	if command.Action == "select" && !validNodeName(command.Name) {
		return fail("invalid")
	}
	e.mu.Lock()
	core, running := e.core, e.running
	e.mu.Unlock()
	if !running || core == nil {
		return fail("stopped")
	}
	if !core.operationMu.TryLock() {
		return fail("busy")
	}
	defer core.operationMu.Unlock()
	core.mu.Lock()
	if core.closed {
		core.mu.Unlock()
		return fail("stopped")
	}
	core.preparing = true
	core.wg.Add(1)
	core.mu.Unlock()
	defer core.wg.Done()
	defer func() { core.mu.Lock(); core.preparing = false; core.mu.Unlock() }()
	ctx, cancel := context.WithTimeout(core.ctx, time.Duration(core.cfg.WakeupTimeout)*time.Second)
	defer cancel()
	if _, err := core.Acquire(ctx); err != nil {
		return fail("unavailable")
	}
	defer core.Release()
	if command.Action == "probe" || command.Action == "fastest" {
		core.mu.Lock()
		nodes := append([]*node(nil), core.nodes...)
		core.mu.Unlock()
		core.checkHealth(ctx, nodes)
		if ctx.Err() != nil {
			return fail("unavailable")
		}
	}
	core.mu.Lock()
	defer core.mu.Unlock()
	if core.closed || core.ctx.Err() != nil {
		return fail("stopped")
	}
	switch command.Action {
	case "select":
		found := false
		for _, n := range core.nodes {
			if n.proxy.Name() == command.Name && n.healthy {
				found = true
				break
			}
		}
		if !found {
			return fail("unavailable")
		}
		core.mode, core.preferred = "fixed", command.Name
		core.legacyFastest = false
		core.fastest = fastestSelection{}
		core.updateHealthLocked(false)
	case "fastest":
		if !hasHealthy(core.nodes) {
			return fail("unavailable")
		}
		core.mode, core.preferred = "fastest", ""
		core.legacyFastest = true
		core.fastest = fastestSelection{}
		core.updateHealthLocked(false)
	}
	return `{"ok":true,"code":"done"}`
}
