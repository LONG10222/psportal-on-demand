// SPDX-License-Identifier: GPL-3.0-only
// Package mobile is the small gomobile-compatible Android/iOS binding surface.
package mobile

import (
	"errors"
	"github.com/psportal/psportal/native/engine"
	"sync"
)

var mu sync.Mutex
var current *engine.Engine

// Start validates configuration and starts the LAN listener. Subscription loading
// and encrypted outbound adapters wake only when an external request arrives.
func Start(configJSON string) error {
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
	mu.Lock()
	defer mu.Unlock()
	if current != nil {
		current.Stop()
		current = nil
	}
}

// Status returns sanitized JSON without subscription URLs or node credentials.
func Status() string {
	mu.Lock()
	defer mu.Unlock()
	if current == nil {
		return `{"running":false,"state":"stopped","active":0}`
	}
	return current.Status()
}
