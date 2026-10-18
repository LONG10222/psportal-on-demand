// SPDX-License-Identifier: GPL-3.0-only
// Package engine implements a LAN-only, on-demand HTTP/CONNECT proxy using
// owned Mihomo outbound adapters. It never changes OS proxy, VPN, DNS or firewall.
package engine

import (
	"encoding/json"
	"sync"
)

type Engine struct {
	mu      sync.Mutex
	cfg     Config
	proxy   *Proxy
	core    *embeddedCore
	running bool
}

func New(cfg Config) (*Engine, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return &Engine{cfg: cfg}, nil
}
func (e *Engine) Start() error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.running {
		return nil
	}
	core := newEmbeddedCore(e.cfg)
	proxy := NewProxy(e.cfg, core)
	if err := proxy.Start(); err != nil {
		core.Close()
		return err
	}
	e.core = core
	e.proxy = proxy
	e.running = true
	return nil
}
func (e *Engine) Stop() {
	e.mu.Lock()
	defer e.mu.Unlock()
	if !e.running {
		return
	}
	// Cancellation starts before waiting for proxy handlers or adapter resources.
	e.core.cancel()
	_ = e.proxy.Stop()
	e.core.Close()
	e.running = false
}
func (e *Engine) Status() string {
	e.mu.Lock()
	defer e.mu.Unlock()
	status := map[string]any{"running": e.running, "state": "stopped", "active": 0, "engine": "mihomo-adapters", "engine_version": "1.19.32", "selection_mode": e.cfg.SelectionMode}
	if e.core != nil {
		for k, v := range e.core.Status() {
			status[k] = v
		}
	}
	if e.proxy != nil {
		status["stats"] = e.proxy.Status()
	}
	result, _ := json.Marshal(status)
	return string(result)
}
