// SPDX-License-Identifier: GPL-3.0-only
// Package engine implements a LAN-only, on-demand HTTP/CONNECT proxy using
// owned Mihomo outbound adapters. It never changes OS proxy, VPN, DNS or firewall.
package engine

import (
	"bytes"
	"encoding/json"
	"errors"
	"net"
	"strconv"
	"sync"
)

type Engine struct {
	lifeMu  sync.Mutex
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
	e.lifeMu.Lock()
	defer e.lifeMu.Unlock()
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
	e.lifeMu.Lock()
	defer e.lifeMu.Unlock()
	e.mu.Lock()
	if !e.running {
		e.mu.Unlock()
		return
	}
	core, proxy := e.core, e.proxy
	e.running = false
	e.mu.Unlock()
	// Cancellation starts before joining owned work. Status never holds the
	// lifecycle lock, so it remains readable while adapters shut down.
	core.cancel()
	_ = proxy.Stop()
	core.Close()
}
func (e *Engine) Status() string {
	e.mu.Lock()
	defer e.mu.Unlock()
	status := map[string]any{"event": "status", "listen_host": e.cfg.ListenHost, "listen_port": e.cfg.ListenPort, "address": net.JoinHostPort(e.cfg.ListenHost, strconv.Itoa(e.cfg.ListenPort)), "connected_clients": 0, "active_connections": 0, "client_ips": []string{}, "nodes": []any{}, "node_management": true, "running": e.running, "state": "stopped", "core_state": "stopped", "selected_node": "", "error": "", "active": 0, "engine": "mihomo-adapters", "engine_version": "1.19.32", "selection_mode": e.cfg.SelectionMode}
	if e.core != nil {
		for k, v := range e.core.Status() {
			status[k] = v
		}
	}
	if e.proxy != nil {
		stats := e.proxy.Status()
		status["stats"] = stats
		for _, key := range []string{"connected_clients", "active_connections", "client_ips"} {
			status[key] = stats[key]
		}
		if e.running {
			switch {
			case status["preparing"] == true:
				status["state"] = "preparing"
			case stats["waking"].(uint64) > 0 || status["core_state"] == "starting":
				status["state"] = "waking"
			case stats["forwarding"].(uint64) > 0:
				status["state"] = "forwarding"
			case status["core_state"] == "error" || status["error"] != "" || stats["error"] != "":
				status["state"] = "error"
				if status["error"] == "" {
					status["error"] = stats["error"]
				}
			default:
				status["state"] = "listening"
			}
		} else {
			status["state"] = "stopped"
		}
	}
	// IPC JSON is not embedded in HTML. Avoid sixfold expansion of valid
	// provider labels so the bounded 1000-node pool fits host status limits.
	var result bytes.Buffer
	encoder := json.NewEncoder(&result)
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(status)
	return string(bytes.TrimSuffix(result.Bytes(), []byte("\n")))
}

// liveCore returns an owned engine reference without holding the lifecycle lock
// across network probes, so status and Stop remain responsive.
func (e *Engine) liveCore() (*embeddedCore, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if !e.running || e.core == nil {
		return nil, errors.New("proxy is not started")
	}
	return e.core, nil
}
func (e *Engine) Prepare() error {
	core, err := e.liveCore()
	if err != nil {
		return err
	}
	err = core.prepare()
	if err == nil {
		e.mu.Lock()
		if e.core == core && e.proxy != nil {
			e.proxy.mu.Lock()
			e.proxy.lastError = ""
			e.proxy.mu.Unlock()
		}
		e.mu.Unlock()
	}
	return err
}
func (e *Engine) TestNodes() error { return e.Prepare() }
func (e *Engine) SelectNode(mode, name string) error {
	core, err := e.liveCore()
	if err != nil {
		return err
	}
	return core.selectNode(mode, name, nil)
}
func (e *Engine) SelectNodeWithThreshold(mode, name string, threshold int) error {
	core, err := e.liveCore()
	if err != nil {
		return err
	}
	return core.selectNode(mode, name, &threshold)
}
