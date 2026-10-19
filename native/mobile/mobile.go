// SPDX-License-Identifier: GPL-3.0-only
// Package mobile is the small gomobile-compatible Android/iOS binding surface.
package mobile

import (
	"bytes"
	"encoding/json"
	"errors"
	"github.com/psportal/psportal/native/engine"
	"sync"
)

var lifecycleMu sync.Mutex
var mu sync.Mutex
var current *engine.Engine

// SubscriptionInfo returns only bounded accounting values provided by the server.
func SubscriptionInfo(url string) string { return engine.SubscriptionInfo(url) }

// Start validates configuration and starts the LAN listener. Subscription loading
// and encrypted outbound adapters wake only when an external request arrives.
func Start(configJSON string) error {
	lifecycleMu.Lock()
	defer lifecycleMu.Unlock()
	cfg, err := engine.ParseConfig(configJSON)
	if err != nil {
		return err
	}
	if cfg.SubscriptionFile != "" {
		return errors.New("mobile supports subscription_url only")
	}
	mu.Lock()
	defer mu.Unlock()
	if current != nil {
		return errors.New("proxy is already started; stop before changing configuration")
	}
	next, err := engine.New(cfg)
	if err != nil {
		return err
	}
	if err = next.Start(); err != nil {
		return err
	}
	current = next
	return nil
}

// Stop cancels in-flight startup and closes owned connections and adapters.
func Stop() {
	lifecycleMu.Lock()
	defer lifecycleMu.Unlock()
	mu.Lock()
	app := current
	current = nil
	mu.Unlock()
	if app != nil {
		app.Stop()
	}
}

// Status preserves the original core-state schema consumed by existing iOS
// hosts. RuntimeStatus exposes the richer listener/traffic state for new hosts.
func Status() string {
	var status map[string]any
	raw := RuntimeStatus()
	if json.Unmarshal([]byte(raw), &status) != nil {
		return raw
	}
	status["service_state"] = status["state"]
	status["state"] = status["core_state"]
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(status)
	return string(bytes.TrimSuffix(encoded.Bytes(), []byte("\n")))
}

// RuntimeStatus returns sanitized service-state JSON without URLs/credentials.
func RuntimeStatus() string {
	mu.Lock()
	app := current
	mu.Unlock()
	if app == nil {
		return `{"event":"status","running":false,"state":"stopped","core_state":"stopped","active":0,"connected_clients":0,"active_connections":0,"client_ips":[],"nodes":[],"node_management":true,"address":"","selected_node":"","error":""}`
	}
	return app.Status()
}

func activeEngine() (*engine.Engine, error) {
	mu.Lock()
	defer mu.Unlock()
	if current == nil {
		return nil, errors.New("proxy is not started")
	}
	return current, nil
}

// Prepare loads and probes live nodes after Start, without restarting the listener.
func Prepare() error {
	app, err := activeEngine()
	if err != nil {
		return err
	}
	return app.Prepare()
}
func TestNodes() error {
	app, err := activeEngine()
	if err != nil {
		return err
	}
	return app.TestNodes()
}
func SelectNode(mode, name string) error {
	app, err := activeEngine()
	if err != nil {
		return err
	}
	return app.SelectNode(mode, name)
}
func SelectNodeWithThreshold(mode, name string, threshold int) error {
	app, err := activeEngine()
	if err != nil {
		return err
	}
	return app.SelectNodeWithThreshold(mode, name, threshold)
}
