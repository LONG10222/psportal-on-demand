// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/netip"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/metacubex/mihomo/adapter"
	"github.com/metacubex/mihomo/common/convert"
	"github.com/metacubex/mihomo/common/yaml"
	C "github.com/metacubex/mihomo/constant"
	mihomolog "github.com/metacubex/mihomo/log"
)

// The embedded engine does not expose upstream diagnostic logs, which can contain endpoints.
func init() { mihomolog.SetLevel(mihomolog.SILENT) }

const subscriptionLimit = 10 * 1024 * 1024

var errStopped = errors.New("proxy is stopping")
var errNoHealthy = errors.New("no healthy proxy node is available")

type node struct {
	proxy    C.Proxy
	healthy  bool
	delayMS  int64
	protocol string
}
type embeddedCore struct {
	cfg       Config
	ctx       context.Context
	cancel    context.CancelFunc
	mu        sync.Mutex
	controlMu sync.Mutex
	manual    string
	fastest   bool
	state     string
	closed    bool
	nodes     []*node
	active    int
	lastUsed  time.Time
	selected  string
	lastError string
	loading   chan struct{}
	loadError error
	wg        sync.WaitGroup
}

func newEmbeddedCore(cfg Config) *embeddedCore {
	ctx, cancel := context.WithCancel(context.Background())
	c := &embeddedCore{cfg: cfg, ctx: ctx, cancel: cancel, state: "stopped", lastUsed: time.Now()}
	c.wg.Add(1)
	go c.maintain()
	return c
}
func (c *embeddedCore) Acquire(ctx context.Context) (string, error) {
	c.mu.Lock()
	if c.closed || c.ctx.Err() != nil {
		c.mu.Unlock()
		return "", errStopped
	}
	if len(c.nodes) > 0 {
		c.active++
		c.mu.Unlock()
		return "", nil
	}
	done := c.loading
	if done == nil {
		done = make(chan struct{})
		c.loading = done
		c.state = "starting"
		c.loadError = nil
		c.wg.Add(1)
		go c.load(done)
	}
	c.mu.Unlock()
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case <-c.ctx.Done():
		return "", errStopped
	case <-done:
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed || c.ctx.Err() != nil {
		return "", errStopped
	}
	if c.loadError != nil {
		return "", c.loadError
	}
	if len(c.nodes) == 0 {
		return "", errNoHealthy
	}
	c.active++
	return "", nil
}
func (c *embeddedCore) Release() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.active > 0 {
		c.active--
	}
	c.lastUsed = time.Now()
}
func (c *embeddedCore) load(done chan struct{}) {
	defer c.wg.Done()
	ctx, cancel := context.WithTimeout(c.ctx, time.Duration(c.cfg.WakeupTimeout)*time.Second)
	defer cancel()
	nodes, err := loadNodes(ctx, c.cfg)
	if err == nil {
		c.checkHealth(ctx, nodes)
		if !hasHealthy(nodes) {
			err = errNoHealthy
		}
	}
	c.mu.Lock()
	if c.closed || c.ctx.Err() != nil {
		err = errStopped
	}
	if err != nil {
		c.loadError = err
		c.lastError = err.Error()
		if c.closed {
			c.state = "stopped"
		} else {
			c.state = "error"
		}
	} else {
		c.nodes = nodes
		c.state = "running"
		c.lastError = ""
		c.lastUsed = time.Now()
	}
	c.loading = nil
	close(done)
	c.mu.Unlock()
	if err != nil {
		closeNodes(nodes)
	}
}
func (c *embeddedCore) Status() map[string]any {
	c.mu.Lock()
	defer c.mu.Unlock()
	list := make([]map[string]any, 0, len(c.nodes))
	for _, n := range c.nodes {
		list = append(list, map[string]any{"name": n.proxy.Name(), "healthy": n.healthy, "delay_ms": n.delayMS, "protocol": n.protocol})
	}
	return map[string]any{"state": c.state, "active": c.active, "selected_node": c.selected, "nodes": list, "error": c.lastError, "manual_node": c.manual, "auto_fastest": c.fastest}
}
func (c *embeddedCore) Close() {
	c.cancel()
	c.mu.Lock()
	c.closed = true
	c.state = "stopped"
	nodes := c.nodes
	c.nodes = nil
	c.mu.Unlock()
	c.wg.Wait()
	closeNodes(nodes)
}
func closeNodes(nodes []*node) {
	for _, n := range nodes {
		_ = n.proxy.Close()
	}
}
func hasHealthy(nodes []*node) bool {
	for _, n := range nodes {
		if n.healthy {
			return true
		}
	}
	return false
}
func (c *embeddedCore) maintain() {
	defer c.wg.Done()
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	lastHealth := time.Now()
	for {
		select {
		case <-c.ctx.Done():
			return
		case now := <-tick.C:
			c.mu.Lock()
			if len(c.nodes) > 0 && c.active == 0 && now.Sub(c.lastUsed) >= time.Duration(c.cfg.IdleSeconds)*time.Second {
				nodes := c.nodes
				c.nodes = nil
				c.state = "stopped"
				c.selected = ""
				c.mu.Unlock()
				closeNodes(nodes)
				continue
			}
			if len(c.nodes) == 0 || now.Sub(lastHealth) < time.Duration(c.cfg.HealthInterval)*time.Second {
				c.mu.Unlock()
				continue
			}
			// A maintenance lease prevents idle teardown during health probes.
			nodes := append([]*node(nil), c.nodes...)
			budget := time.Duration(c.cfg.WakeupTimeout) * time.Second
			if c.active == 0 {
				remaining := time.Duration(c.cfg.IdleSeconds)*time.Second - now.Sub(c.lastUsed)
				if remaining < budget {
					budget = remaining
				}
			}
			c.active++
			c.mu.Unlock()
			probeCtx, cancel := context.WithTimeout(c.ctx, budget)
			c.checkHealth(probeCtx, nodes)
			cancel()
			c.mu.Lock()
			c.active-- // Maintenance is not client traffic; preserve lastUsed.
			c.mu.Unlock()
			lastHealth = now
		}
	}
}
func (c *embeddedCore) checkHealth(ctx context.Context, nodes []*node) {
	var wg sync.WaitGroup
	sem := make(chan struct{}, 8)
	for _, n := range nodes {
		select {
		case sem <- struct{}{}:
		case <-ctx.Done():
			wg.Wait()
			return
		}
		wg.Add(1)
		go func(n *node) {
			defer wg.Done()
			defer func() { <-sem }()
			started := time.Now()
			ok := probeNode(ctx, n.proxy, c.cfg)
			delay := time.Since(started).Milliseconds()
			if delay < 1 {
				delay = 1
			}
			if !ok {
				delay = 0
			}
			if ctx.Err() != nil {
				return
			} // A cancelled batch is not a failed node probe.
			c.mu.Lock()
			n.healthy = ok
			n.delayMS = delay
			c.mu.Unlock()
		}(n)
	}
	wg.Wait()
}

// DialExternal pins a verified public numeric destination inside the encrypted
// proxy protocol. The peer never re-resolves the client's hostname, closing the
// DNS-rebinding gap. HTTP Host and TLS SNI remain end-to-end application bytes.
func (c *embeddedCore) DialExternal(ctx context.Context, host string, port int) (net.Conn, error) {
	addrs, err := publicAddresses(ctx, host)
	if err != nil {
		return nil, err
	}
	c.mu.Lock()
	nodes := make([]*node, 0, len(c.nodes))
	for _, n := range c.nodes {
		if n.healthy {
			nodes = append(nodes, n)
		}
	}
	manual, fastest := c.manual, c.fastest
	if manual != "" {
		filtered := nodes[:0]
		for _, n := range nodes {
			if n.proxy.Name() == manual {
				filtered = append(filtered, n)
			}
		}
		nodes = filtered
	} else if fastest {
		sort.SliceStable(nodes, func(i, j int) bool {
			return nodes[i].delayMS > 0 && (nodes[j].delayMS == 0 || nodes[i].delayMS < nodes[j].delayMS)
		})
	}
	c.mu.Unlock()
	for _, n := range nodes {
		for _, ip := range addrs {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			md := &C.Metadata{NetWork: C.TCP, Type: C.HTTP, DstIP: ip, DstPort: uint16(port)}
			attemptCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
			conn, err := n.proxy.DialContext(attemptCtx, md)
			cancel()
			if err == nil {
				c.mu.Lock()
				c.selected = n.proxy.Name()
				c.mu.Unlock()
				return conn, nil
			}
		}
		c.mu.Lock()
		n.healthy = false
		c.mu.Unlock()
		if c.cfg.SelectionMode == "fixed" || manual != "" {
			break
		}
	}
	return nil, errNoHealthy
}

func loadNodes(ctx context.Context, cfg Config) ([]*node, error) {
	var raw []byte
	var err error
	if cfg.SubscriptionFile != "" {
		raw, err = readSubscriptionFile(ctx, cfg.SubscriptionFile)
	} else {
		raw, err = downloadSubscription(ctx, cfg.SubscriptionURL)
	}
	if err != nil {
		return nil, err
	}
	nodes, err := parseNodes(raw)
	if err != nil {
		return nil, err
	}
	orderNodes(nodes, cfg)
	if cfg.SelectionMode == "fixed" {
		var chosen *node
		for _, n := range nodes {
			if n.proxy.Name() == cfg.PreferredNode {
				chosen = n
			} else {
				_ = n.proxy.Close()
			}
		}
		if chosen == nil {
			return nil, errors.New("fixed node is missing from the subscription")
		}
		nodes = []*node{chosen}
	}
	return nodes, nil
}

// readSubscriptionFile is desktop-only and reads one bounded snapshot in memory.
func readSubscriptionFile(ctx context.Context, path string) ([]byte, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() == 0 || info.Size() > subscriptionLimit {
		return nil, errors.New("local subscription must be a regular file of 1 byte to 10 MiB")
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, errors.New("local subscription file could not be opened")
	}
	defer file.Close()
	before, err := file.Stat()
	if err != nil || !before.Mode().IsRegular() || before.Size() == 0 || before.Size() > subscriptionLimit {
		return nil, errors.New("local subscription must be a regular file of 1 byte to 10 MiB")
	}
	body, err := io.ReadAll(io.LimitReader(file, subscriptionLimit+1))
	if err != nil || len(body) == 0 || len(body) > subscriptionLimit {
		return nil, errors.New("local subscription read failed or exceeds 10 MiB")
	}
	after, err := file.Stat()
	if err != nil || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
		return nil, errors.New("local subscription changed while being read")
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	return body, nil
}

func downloadSubscription(ctx context.Context, rawURL string) ([]byte, error) {
	transport := &http.Transport{Proxy: nil, DialContext: publicTCPDial, TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 15 * time.Second, DisableKeepAlives: true}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 20 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("subscription redirects are disabled") }}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, errors.New("invalid subscription URL")
	}
	request.Header.Set("User-Agent", "clash.meta/1.19.32 PSPortal-Native/0.2")
	response, err := client.Do(request)
	if err != nil {
		return nil, errors.New("subscription HTTPS download failed (public destination and no redirects required)")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, errors.New("subscription server did not return HTTP 200")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, subscriptionLimit+1))
	if err != nil {
		return nil, errors.New("subscription read failed")
	}
	if len(body) == 0 || len(body) > subscriptionLimit {
		return nil, errors.New("subscription is empty or exceeds 10 MiB")
	}
	return body, nil
}

var allowedTypes = map[string]bool{"ss": true, "ssr": true, "socks5": true, "http": true, "vmess": true, "vless": true, "snell": true, "trojan": true, "hysteria": true, "hysteria2": true, "tuic": true, "anytls": true}

func parseNodes(raw []byte) ([]*node, error) {
	var schema struct {
		Proxies []map[string]any `yaml:"proxies"`
	}
	err := yaml.Unmarshal(raw, &schema)
	if err != nil || schema.Proxies == nil {
		schema.Proxies, err = convert.ConvertsV2Ray(raw)
	}
	if err != nil || len(schema.Proxies) == 0 || len(schema.Proxies) > 1000 {
		return nil, errors.New("subscription must contain 1 to 1000 supported proxy nodes")
	}
	nodes := []*node{}
	seen := map[string]bool{}
	fail := func() ([]*node, error) {
		closeNodes(nodes)
		return nil, errors.New("subscription contains an invalid, duplicate or unsafe proxy node")
	}
	for _, mapping := range schema.Proxies {
		kind, _ := mapping["type"].(string)
		if !allowedTypes[kind] {
			continue
		}
		name, _ := mapping["name"].(string)
		if !validNodeName(name) || seen[name] || unsafeNodeOptions(mapping) {
			return fail()
		}
		seen[name] = true
		server, _ := mapping["server"].(string)
		if k := Destination(server); k != "external" && k != "name" {
			return fail()
		}
		// No UDP application forwarding or routing overrides from subscriptions.
		mapping["udp"] = false
		mapping["tfo"] = false
		mapping["mptcp"] = false
		proxy, err := adapter.ParseProxy(mapping, adapter.WithDialerForAPI(protectedDialer{}), adapter.WithProviderName("SUBSCRIPTION"))
		if err != nil {
			return fail()
		}
		nodes = append(nodes, &node{proxy: proxy, protocol: kind})
	}
	if len(nodes) == 0 {
		return nil, errors.New("subscription has no supported proxy nodes")
	}
	return nodes, nil
}

// Subscription data cannot inject file reads, host-network selection or another
// routing graph. Unused top-level config, rules, listeners and providers are ignored.
func unsafeNodeOptions(value any) bool {
	switch v := value.(type) {
	case map[string]any:
		for key, value := range v {
			switch strings.ToLower(key) {
			case "dialer-proxy", "interface-name", "routing-mark", "certificate", "private-key", "ca", "ca-str", "client-cert", "client-key":
				return true
			}
			if unsafeNodeOptions(value) {
				return true
			}
		}
	case map[any]any:
		for key, value := range v {
			if s, ok := key.(string); ok {
				if unsafeNodeOptions(map[string]any{s: value}) {
					return true
				}
			} else {
				return true
			}
		}
	case []any:
		for _, item := range v {
			if unsafeNodeOptions(item) {
				return true
			}
		}
	}
	return false
}

var hk = regexp.MustCompile(`(?i)香港|🇭🇰|\bHK\b|Hong[ -]?Kong`)
var jp = regexp.MustCompile(`(?i)日本|东京|大阪|🇯🇵|\bJP\b|Japan`)

func orderNodes(nodes []*node, cfg Config) {
	rank := func(n *node) int {
		if cfg.SelectionMode != "auto" && n.proxy.Name() == cfg.PreferredNode {
			return -1
		}
		if hk.MatchString(n.proxy.Name()) {
			return 0
		}
		if jp.MatchString(n.proxy.Name()) {
			return 1
		}
		return 2
	}
	sort.SliceStable(nodes, func(i, j int) bool { return rank(nodes[i]) < rank(nodes[j]) })
}
func probeNode(parent context.Context, proxy C.Proxy, cfg Config) bool {
	ctx, cancel := context.WithTimeout(parent, time.Duration(cfg.HealthTimeout)*time.Millisecond)
	defer cancel()
	transport := &http.Transport{Proxy: nil, DisableKeepAlives: true, TLSHandshakeTimeout: time.Duration(cfg.HealthTimeout) * time.Millisecond, DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		host, port, err := net.SplitHostPort(address)
		if err != nil {
			return nil, err
		}
		p, err := strconv.Atoi(port)
		if err != nil {
			return nil, err
		}
		ips, err := publicAddresses(ctx, host)
		if err != nil {
			return nil, err
		}
		return proxy.DialContext(ctx, &C.Metadata{NetWork: C.TCP, Type: C.HTTP, DstIP: ips[0], DstPort: uint16(p)})
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("health redirects disabled") }}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, cfg.HealthURL, nil)
	if err != nil {
		return false
	}
	res, err := client.Do(req)
	if err != nil {
		return false
	}
	defer res.Body.Close()
	return res.StatusCode == http.StatusNoContent
}

func publicAddresses(ctx context.Context, host string) ([]netip.Addr, error) {
	return publicAddressesWithResolver(ctx, systemResolver, host)
}
func publicAddressesWithResolver(ctx context.Context, resolver ipResolver, host string) ([]netip.Addr, error) {
	host = NormalizeHost(host)
	switch Destination(host) {
	case "external":
		addr, err := netip.ParseAddr(host)
		if err != nil {
			return nil, ErrDestinationDenied
		}
		return []netip.Addr{addr}, nil
	case "name":
	default:
		return nil, ErrDestinationDenied
	}
	ips, err := resolver.LookupIPAddr(ctx, host)
	if err != nil || len(ips) == 0 {
		return nil, ErrResolutionFailed
	}
	addresses := []netip.Addr{}
	for _, ip := range ips {
		if ip.Zone != "" {
			return nil, ErrDestinationDenied
		}
		addr, ok := netip.AddrFromSlice(ip.IP)
		if !ok {
			return nil, ErrResolutionFailed
		}
		if Destination(addr.String()) != "external" {
			return nil, ErrDestinationDenied
		}
		addresses = append(addresses, addr)
	}
	return addresses, nil
}
func publicTCPDial(ctx context.Context, network, address string) (net.Conn, error) {
	if network != "tcp" && network != "tcp4" && network != "tcp6" {
		return nil, errors.New("TCP required")
	}
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	ips, err := publicAddresses(ctx, host)
	if err != nil {
		return nil, err
	}
	var last error
	for _, ip := range ips {
		conn, err := (&net.Dialer{Timeout: 15 * time.Second}).DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
		if err == nil {
			return conn, nil
		}
		last = err
	}
	return nil, last
}

type protectedDialer struct{}

func (protectedDialer) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	return publicTCPDial(ctx, network, address)
}
func (protectedDialer) ListenPacket(ctx context.Context, network, address string, remote netip.AddrPort) (net.PacketConn, error) {
	if !remote.IsValid() || Destination(remote.Addr().String()) != "external" {
		return nil, ErrDestinationDenied
	}
	conn, err := (&net.ListenConfig{}).ListenPacket(ctx, network, address)
	if err != nil {
		return nil, err
	}
	return &publicPacketConn{PacketConn: conn, remote: remote}, nil
}

type publicPacketConn struct {
	net.PacketConn
	remote netip.AddrPort
}

func (c *publicPacketConn) WriteTo(p []byte, a net.Addr) (int, error) {
	peer, err := netip.ParseAddrPort(a.String())
	if err != nil || peer != c.remote || Destination(peer.Addr().String()) != "external" {
		return 0, ErrDestinationDenied
	}
	return c.PacketConn.WriteTo(p, a)
}
func (c *publicPacketConn) ReadFrom(p []byte) (int, net.Addr, error) {
	for {
		n, addr, err := c.PacketConn.ReadFrom(p)
		if err != nil {
			return n, addr, err
		}
		peer, e := netip.ParseAddrPort(addr.String())
		if e == nil && peer == c.remote {
			return n, addr, nil
		}
	}
}
