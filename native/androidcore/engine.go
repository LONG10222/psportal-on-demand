// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/metacubex/mihomo/adapter/outboundgroup"
	N "github.com/metacubex/mihomo/common/net"
	"github.com/metacubex/mihomo/component/resolver"
	MC "github.com/metacubex/mihomo/config"
	C "github.com/metacubex/mihomo/constant"
	"github.com/metacubex/mihomo/hub/executor"
	"github.com/metacubex/mihomo/log"
	"github.com/metacubex/mihomo/tunnel"
	"github.com/metacubex/mihomo/tunnel/statistic"
	"github.com/psportal/psportal/native/engine"
	"io"
	"net"
	"net/netip"
	"strconv"
	"strings"
	"sync"
	"time"
)

var ownership sync.Mutex
var owner *Engine

// Engine exclusively owns upstream Mihomo's global executor for one session.
type Engine struct {
	lifeMu           sync.Mutex
	mu               sync.Mutex
	cfg              Config
	ctx              context.Context
	cancel           context.CancelFunc
	current          *MC.Config
	profile          profile
	source           []byte
	proxy            *engine.Proxy
	active           int
	state, lastError string
	errorCode        string
	lastUsed         time.Time
	running, closed  bool
	loading          chan struct{}
	loadError        error
	wg               sync.WaitGroup
	loader           func(context.Context, string) ([]byte, error)
	groupSelections  map[string]string // Session-local; retained across idle unload, never persisted.
}

func New(cfg Config) (*Engine, error) {
	if err := cfg.Config.Validate(); err != nil {
		return nil, err
	}
	if cfg.RoutingMode != "rule" && cfg.RoutingMode != "global" && cfg.RoutingMode != "direct" {
		return nil, errors.New("invalid routing mode")
	}
	ctx, cancel := context.WithCancel(context.Background())
	return &Engine{cfg: cfg, ctx: ctx, cancel: cancel, state: "stopped", loader: download}, nil
}
func (e *Engine) Start() error {
	e.lifeMu.Lock()
	defer e.lifeMu.Unlock()
	ownership.Lock()
	defer ownership.Unlock()
	if owner != nil {
		return errors.New("another Android Mihomo session is running")
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.closed {
		return errors.New("session is closed")
	}
	activateSocketPolicy(e)
	log.SetLevel(log.SILENT)
	if e.cfg.LANEnabled {
		p := engine.NewProxy(e.cfg.Config, e)
		if err := p.Start(); err != nil {
			retireSocketPolicy(e)
			return err
		}
		e.proxy = p
	}
	owner = e
	e.running = true
	e.lastUsed = time.Now()
	e.wg.Add(1)
	go e.maintain()
	return nil
}
func (e *Engine) Stop() {
	e.cancel()
	e.lifeMu.Lock()
	defer e.lifeMu.Unlock()
	e.stopPhoneVPNLocked()
	e.mu.Lock()
	e.closed = true
	e.running = false
	p := e.proxy
	core := e.current
	e.mu.Unlock()
	if p != nil {
		_ = p.Stop()
	}
	closeRuntime(core)
	e.wg.Wait()
	e.mu.Lock()
	e.unloadLocked()
	e.source = nil
	e.profile = profile{}
	e.groupSelections = nil
	e.state = "stopped"
	e.mu.Unlock()
	retireSocketPolicy(e)
	ownership.Lock()
	if owner == e {
		owner = nil
	}
	ownership.Unlock()
}
func (e *Engine) Acquire(ctx context.Context) (string, error) {
	e.mu.Lock()
	if e.closed || e.ctx.Err() != nil {
		e.mu.Unlock()
		return "", errors.New("proxy is stopping")
	}
	if e.current != nil {
		e.active++
		e.mu.Unlock()
		return "", nil
	}
	done := e.loading
	if done == nil {
		done = make(chan struct{})
		e.loading = done
		e.state = "starting"
		e.loadError = nil
		e.wg.Add(1)
		go e.load(done)
	}
	e.mu.Unlock()
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case <-e.ctx.Done():
		return "", e.ctx.Err()
	case <-done:
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.closed || e.ctx.Err() != nil {
		return "", errors.New("proxy is stopping")
	}
	if e.loadError != nil {
		return "", e.loadError
	}
	if e.current == nil {
		return "", errors.New("Mihomo did not initialize")
	}
	e.active++
	return "", nil
}
func (e *Engine) Release() {
	e.mu.Lock()
	if e.active > 0 {
		e.active--
	}
	e.lastUsed = time.Now()
	e.mu.Unlock()
}
func (e *Engine) load(done chan struct{}) {
	defer e.wg.Done()
	ctx, cancel := context.WithTimeout(e.ctx, time.Duration(e.cfg.WakeupTimeout)*time.Second)
	defer cancel()
	e.mu.Lock()
	body := e.source
	e.mu.Unlock()
	var err error
	code := "download_failed"
	if len(body) == 0 {
		body, err = e.loader(ctx, e.cfg.SubscriptionURL)
	}
	var p profile
	if err == nil {
		p, err = sanitizeProfile(body, e.cfg)
		code = "profile_invalid"
		if err != nil {
			if strings.Contains(err.Error(), "unsupported") {
				code = "profile_unsupported"
			}
			if strings.Contains(err.Error(), "selection_mode auto") {
				code = "profile_selection_required"
			}
		}
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if err == nil && ctx.Err() != nil {
		err = ctx.Err()
	}
	if err == nil && !e.closed {
		// Reapply only choices made in this exact session and still present in the
		// sanitized inline group. No choice can escape its original membership.
		for _, group := range p.raw.ProxyGroup {
			name, _ := group["name"].(string)
			if choice, ok := e.groupSelections[name]; ok && group["type"] == "select" {
				if containsGroupChoice(group, choice) {
					group["default-selected"] = choice
				}
			}
		}
		var parsed *MC.Config
		parsed, err = MC.ParseRawConfig(p.raw)
		if err == nil {
			err = installUDPGuards(parsed)
		}
		if err == nil {
			if ctx.Err() != nil {
				closeConfig(parsed)
				err = ctx.Err()
			} else {
				executor.ApplyConfig(parsed, true)
				if !e.cfg.PhoneVPN {
					resolver.DefaultResolver = publicResolver{}
					resolver.ProxyServerHostResolver = publicResolver{}
					resolver.DirectHostResolver = publicResolver{}
				} else {
					installOwnedPhoneDNS()
				}
				activateRuntime(parsed)
				e.current = parsed
				e.profile = p
				e.source = body
				e.state = "running"
				e.lastError = ""
				e.errorCode = ""
				e.lastUsed = time.Now()
			}
		} else {
			err = errors.New("Mihomo rejected the bounded subscription configuration")
		}
	}
	if e.closed || e.ctx.Err() != nil {
		err = errors.New("proxy is stopping")
	}
	e.loadError = err
	if err != nil {
		e.lastError = err.Error()
		e.errorCode = code
		e.state = "error"
	}
	e.loading = nil
	close(done)
}
func closeConfig(cfg *MC.Config) {
	if cfg == nil {
		return
	}
	closeRuntime(cfg)
	for _, p := range cfg.Providers {
		if c, ok := p.(io.Closer); ok {
			_ = c.Close()
		}
	}
	for _, p := range cfg.RuleProviders {
		if c, ok := p.(io.Closer); ok {
			_ = c.Close()
		}
	}
	for _, p := range cfg.Proxies {
		_ = p.Close()
	}
}
func (e *Engine) unloadLocked() {
	if e.current == nil {
		return
	}
	tunnel.SuspendIngress()
	tunnel.OnSuspend()
	statistic.DefaultManager.Range(func(t statistic.Tracker) bool { _ = t.Close(); return true })
	closeRuntime(e.current)
	closeOwnedPhoneDNS()
	tunnel.WaitIngress()
	closeConfig(e.current)
	if resolver.DefaultResolver != nil {
		resolver.DefaultResolver.ResetConnection()
	}
	if resolver.ProxyServerHostResolver != nil {
		resolver.ProxyServerHostResolver.ResetConnection()
	}
	if resolver.DirectHostResolver != nil {
		resolver.DirectHostResolver.ResetConnection()
	}
	resolver.DefaultResolver = nil
	resolver.ProxyServerHostResolver = nil
	resolver.DirectHostResolver = nil
	resolver.DefaultService = nil
	resolver.DefaultHostMapper = nil
	tunnel.UpdateProxies(nil, nil)
	tunnel.UpdateRules(nil, nil, nil)
	e.current = nil
	e.state = "stopped"
}
func (e *Engine) maintain() {
	defer e.wg.Done()
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	for {
		select {
		case <-e.ctx.Done():
			return
		case now := <-tick.C:
			if e.phoneVPNActive() {
				continue
			}
			e.mu.Lock()
			if e.current != nil && e.active == 0 && now.Sub(e.lastUsed) >= time.Duration(e.cfg.IdleSeconds)*time.Second {
				e.unloadLocked()
			}
			e.mu.Unlock()
		}
	}
}
func (e *Engine) Prepare() error {
	ctx, cancel := context.WithTimeout(e.ctx, time.Duration(e.cfg.WakeupTimeout)*time.Second)
	defer cancel()
	_, err := e.Acquire(ctx)
	if err == nil {
		e.Release()
	}
	return err
}

// Actual rules are evaluated by Mihomo; this wrapper only validates destination.
func (e *Engine) DialExternal(ctx context.Context, host string, port int) (net.Conn, error) {
	ips, err := publicAddresses(ctx, host)
	if err != nil {
		return nil, err
	}
	m := &C.Metadata{NetWork: C.TCP, Type: C.HTTP, DNSMode: C.DNSNormal, DstIP: ips[0].Unmap(), DstPort: uint16(port)}
	if _, err := netip.ParseAddr(host); err != nil {
		m.Host = host
	}
	return e.openTunnel(ctx, m)
}
func (e *Engine) openTunnel(ctx context.Context, m *C.Metadata) (net.Conn, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	client, server := N.Pipe()
	e.mu.Lock()
	if e.current == nil || e.closed {
		e.mu.Unlock()
		client.Close()
		server.Close()
		return nil, errors.New("Mihomo is stopped")
	}
	e.wg.Add(1)
	e.mu.Unlock()
	go func() { defer e.wg.Done(); tunnel.Tunnel.HandleTCPConn(server, m) }()
	return client, nil
}
func (e *Engine) TestNodes() error {
	if err := e.Prepare(); err != nil {
		return err
	}
	e.mu.Lock()
	if e.current == nil || e.closed {
		e.mu.Unlock()
		return errors.New("Mihomo is stopped")
	}
	e.active++
	e.wg.Add(1)
	defer e.wg.Done()
	proxies := []C.Proxy{}
	for _, name := range e.profile.names {
		proxies = append(proxies, e.current.Proxies[name])
	}
	e.mu.Unlock()
	defer e.Release()
	ctx, cancel := context.WithTimeout(e.ctx, time.Duration(e.cfg.HealthTimeout)*time.Millisecond)
	defer cancel()
	var wg sync.WaitGroup
	gate := make(chan struct{}, 8)
loop:
	for _, p := range proxies {
		select {
		case <-ctx.Done():
			break loop
		case gate <- struct{}{}:
			wg.Add(1)
			go func(p C.Proxy) {
				defer wg.Done()
				defer func() { <-gate }()
				_, _ = p.URLTest(ctx, e.cfg.HealthURL, nil)
			}(p)
		}
	}
	wg.Wait()
	return ctx.Err()
}
func (e *Engine) SelectNodeWithThreshold(mode, name string, threshold int) error {
	if threshold < 0 || threshold > 60000 {
		return errors.New("invalid switch threshold")
	}
	if mode != "auto" && mode != "prefer" && mode != "fixed" && mode != "fastest" {
		return errors.New("invalid node selection mode")
	}
	if err := e.Prepare(); err != nil {
		return err
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.active != 0 || e.phoneVPNActive() {
		return errors.New("finish active connections before changing node selection")
	}
	if e.current == nil || e.closed {
		return errors.New("Mihomo is stopped")
	}
	if mode == "prefer" && name != e.cfg.PreferredNode {
		return errors.New("stop before changing the preferred fallback order")
	}
	if threshold != e.cfg.SwitchThresholdMS {
		return errors.New("stop before changing Mihomo URL-test tolerance")
	}
	target := name
	if mode == "prefer" {
		target = preferGroup
	}
	groupName := "GLOBAL"
	if e.profile.generated {
		groupName = generatedGroup
		if mode == "auto" {
			target = autoGroup
		}
		if mode == "fastest" {
			target = fastestGroup
		}
	} else {
		return errors.New("use the subscription's own policy groups for automatic selection")
	}
	p := e.current.Proxies[groupName]
	selector, ok := originalAdapter(p).(*outboundgroup.Selector)
	if !ok {
		return errors.New("subscription GLOBAL group is not selectable")
	}
	if err := selector.Set(target); err != nil {
		return errors.New("selected node is not in this policy group")
	}
	e.cfg.SelectionMode = mode
	e.cfg.PreferredNode = name
	e.cfg.SwitchThresholdMS = threshold
	return nil
}
func (e *Engine) Status() string {
	e.mu.Lock()
	defer e.mu.Unlock()
	status := map[string]any{"event": "status", "running": e.running, "state": "stopped", "core_state": e.state, "engine": "mihomo-full-core", "engine_version": "1.19.32", "full_core": true, "routing_mode": e.cfg.RoutingMode, "lan_enabled": e.cfg.LANEnabled, "phone_vpn_requested": e.cfg.PhoneVPN, "selection_mode": e.cfg.SelectionMode, "active": e.active, "active_connections": 0, "connected_clients": 0, "client_ips": []string{}, "nodes": []any{}, "node_management": len(e.source) == 0 || e.profile.generated, "node_policy": "mihomo-native", "error": e.lastError, "error_code": e.errorCode, "address": "", "selected_node": "", "profile_policy": "bounded-inline", "ignored_profile_settings": e.profile.ignored}
	if e.running {
		status["state"] = "listening"
	}
	nodes := []map[string]any{}
	if e.current != nil {
		for _, name := range e.profile.names {
			p := e.current.Proxies[name]
			nodes = append(nodes, map[string]any{"name": name, "healthy": p.AliveForTestUrl(e.cfg.HealthURL), "delay_ms": p.LastDelayForTestUrl(e.cfg.HealthURL), "protocol": p.Type().String(), "udp_supported": originalAdapter(p).SupportUDP()})
		}
		group := "GLOBAL"
		if e.profile.generated {
			group = generatedGroup
		}
		if p := e.current.Proxies[group]; p != nil {
			if g, ok := originalAdapter(p).(interface{ Now() string }); ok {
				status["selected_node"] = g.Now()
			}
		}
	}
	groups := []map[string]any{}
	groupManagement := false
	if e.current != nil {
		for _, g := range e.profile.raw.ProxyGroup {
			name, _ := g["name"].(string)
			p := e.current.Proxies[name]
			if p == nil {
				continue
			}
			selected := ""
			if current, ok := originalAdapter(p).(interface{ Now() string }); ok {
				selected = current.Now()
			}
			_, isSelector := originalAdapter(p).(*outboundgroup.Selector)
			selectable := !e.profile.generated && isSelector && g["type"] == "select"
			groupManagement = groupManagement || selectable
			groups = append(groups, map[string]any{"name": name, "type": p.Type().String(), "selected": selected, "selectable": selectable, "choice_count": len(groupChoices(g))})
		}
	}
	status["policy_groups"] = groups
	status["group_management"] = groupManagement
	status["selected_group"] = "GLOBAL"
	if e.profile.generated {
		status["selected_group"] = generatedGroup
	}
	up, down := statistic.DefaultManager.Total()
	status["upload_bytes"] = up
	status["download_bytes"] = down
	status["nodes"] = nodes
	if e.proxy != nil {
		status["address"] = net.JoinHostPort(e.cfg.ListenHost, strconv.Itoa(e.cfg.ListenPort))
		stats := e.proxy.Status()
		status["stats"] = stats
		for _, key := range []string{"active_connections", "connected_clients", "client_ips"} {
			status[key] = stats[key]
		}
		if e.running && stats["forwarding"].(uint64) > 0 {
			status["state"] = "forwarding"
		}
	}
	if e.running && e.state == "starting" {
		status["state"] = "waking"
	}
	if e.running && e.lastError != "" {
		status["state"] = "error"
	}
	raw, _ := json.Marshal(status)
	return string(raw)
}
