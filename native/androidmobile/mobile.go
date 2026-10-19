// SPDX-License-Identifier: GPL-3.0-only
// Package androidmobile exposes the Android-only full Mihomo engine to gomobile.
package androidmobile

import (
	"errors"
	"github.com/psportal/psportal/native/androidcore"
	"github.com/psportal/psportal/native/engine"
	"sync"
)

var lifecycleMu sync.Mutex
var mu sync.Mutex
var current *androidcore.Engine

func Start(text string) error {
	lifecycleMu.Lock()
	defer lifecycleMu.Unlock()
	cfg, err := androidcore.ParseConfig(text)
	if err != nil {
		return err
	}
	mu.Lock()
	defer mu.Unlock()
	if current != nil {
		return errors.New("proxy already started")
	}
	next, err := androidcore.New(cfg)
	if err != nil {
		return err
	}
	if err = next.Start(); err != nil {
		return err
	}
	current = next
	return nil
}
func Stop() {
	lifecycleMu.Lock()
	defer lifecycleMu.Unlock()
	mu.Lock()
	e := current
	current = nil
	mu.Unlock()
	if e != nil {
		e.Stop()
	}
}
func activeEngine() (*androidcore.Engine, error) {
	mu.Lock()
	defer mu.Unlock()
	if current == nil {
		return nil, errors.New("proxy is stopped")
	}
	return current, nil
}
func RuntimeStatus() string {
	e, err := activeEngine()
	if err != nil {
		return `{"event":"status","running":false,"state":"stopped","core_state":"stopped","engine":"mihomo-full-core","engine_version":"1.19.32","full_core":true,"active":0,"connected_clients":0,"active_connections":0,"client_ips":[],"nodes":[],"node_management":true,"error":""}`
	}
	return e.Status()
}
func Prepare() error {
	e, err := activeEngine()
	if err != nil {
		return err
	}
	return e.Prepare()
}
func TestNodes() error {
	e, err := activeEngine()
	if err != nil {
		return err
	}
	return e.TestNodes()
}
func SelectNodeWithThreshold(mode, name string, threshold int) error {
	e, err := activeEngine()
	if err != nil {
		return err
	}
	return e.SelectNodeWithThreshold(mode, name, threshold)
}
func SubscriptionInfo(url string) string { return engine.SubscriptionInfo(url) }
